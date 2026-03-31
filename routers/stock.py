from math import ceil
import math
import asyncio
import json
from fastapi import FastAPI, HTTPException, Depends, APIRouter, Query, File, UploadFile
from sqlalchemy.orm import Session, selectinload, aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func, or_
from fastapi.responses import JSONResponse, FileResponse
from datetime import datetime, timedelta
from models.stock import OperateLog, StocktakeSession, StocktakeItem, ProductInfo, ProductSnapshot, Job
from routers.product import get_image_url
from schemas.stock import (
    StocktakeSessionOut,
    StocktakeUpload,
    StocktakeItemOut, 
    StocktakeItemBase, 
    StocktakeSessionWithItems,
    StockByLocationResponse,
    ProductInfoOut,
    StocktakeSummaryResponse,
    Pagination,
    StocktakeItemSummaryResponse,
    ProductInfoResponse,
    StocktakeItemOutV2,
    StocktakeItemSummaryResponseV2,
    JobOut
)
from collections import defaultdict
from database import get_db_stock
import traceback
from typing import Optional, List, Dict
from fastapi.encoders import jsonable_encoder
from uuid import UUID
from helper import log_and_save
import pandas as pd
import os
import tempfile
from worker.app.celery_app import celery_app
import uuid
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


router = APIRouter(prefix="/stock", tags=["Stock"])

# 用于记录操作日志
async def log_operation(db: AsyncSession, api_name: str, request_data, response_data):
    try:
        log_and_save('INFO', f"api_name: {api_name} request_data: {request_data} response_data: {response_data}")
        log = OperateLog(
            api_name=api_name,
            request_payload=jsonable_encoder(request_data),
            response_payload=jsonable_encoder(response_data),
            create_time=datetime.now()
        )
        db.add(log)
        await db.commit()
    except:
        pass  # 失败也不抛出

def _get_s3_client():
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.getenv("S3_ACCESS_KEY", "minio")
    secret_key = os.getenv("S3_SECRET_KEY", "minio123456")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

def _ensure_bucket(client, bucket: str):
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchBucket"}:
            client.create_bucket(Bucket=bucket)
        else:
            raise

@router.post("/async")
async def upload_async(data: StocktakeUpload, db: AsyncSession = Depends(get_db_stock)):
    payload = jsonable_encoder(data)
    job_id = str(uuid.uuid4())
    payload_key = f"stocktake/{job_id}.json"
    bucket = os.getenv("S3_BUCKET", "jobs")
    s3_client = _get_s3_client()
    await asyncio.to_thread(_ensure_bucket, s3_client, bucket)
    payload_bytes = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    await asyncio.to_thread(
        s3_client.put_object,
        Bucket=bucket,
        Key=payload_key,
        Body=payload_bytes,
        ContentType="application/json",
    )

    job = Job(id=job_id, status="pending", payload_key=payload_key) # payload 已包含 store
    db.add(job)
    await db.commit()
    celery_app.send_task(
        "process_job",
        args=[job_id],
        queue="default",
    )
    return {"job_id": job_id, "status": "pending"}

@router.post("/", response_model=StocktakeSessionOut)
async def upload_stocktake(data: StocktakeUpload, db: AsyncSession = Depends(get_db_stock)):
    try:
        session_id = data.id
        #user_id = data.user_id

        # 删除旧记录
        await db.execute(delete(StocktakeItem).where(StocktakeItem.session_id == session_id))
        await db.execute(delete(StocktakeSession).where(StocktakeSession.id == session_id))
        now = datetime.now()
        session_creator = data.stocktake[0].user_id if data.stocktake else "system"
        session = StocktakeSession(
            id=session_id,
            device_id=data.deviceId,
            timestamp=data.timestamp,
            store=data.store,
            creator_id=str(session_creator),
            modifier_id=str(session_creator),
            create_time=now,
            update_time=now
        )
        db.add(session)

        for item in data.stocktake:
            raw_barcode = item.barcode or ""
            barcode = raw_barcode.strip()
            if not barcode:
                raise HTTPException(status_code=400, detail="barcode不能为空")
            db_item = StocktakeItem(
                id=item.id,
                session_id=session_id,
                location=item.location,
                barcode=barcode,
                qty=item.qty,
                time=item.time,
                store=item.store or data.store,
                creator_id=str(item.user_id),
                modifier_id=str(item.user_id),
                create_time=now,
                update_time=now
            )
            db.add(db_item)

        await db.commit()
        await db.refresh(session)

        result = {"status": "success", "session_id": session.id, "store": session.store}
        await log_operation(db, "POST /", data.model_dump(), result)
        return session

    except IntegrityError as e:
        await db.rollback()
        result = {"status": "error", "detail": "Duplicate ID or constraint violation", "info": str(e.orig)}
        print(f"IntegrityError error: {result} e: {e}")
        await log_operation(db, "POST /", data.model_dump(), result)
        raise HTTPException(status_code=400, detail=result)

    except Exception as e:
        await db.rollback()
        tb = traceback.format_exc()
        result = {"status": "error", "detail": str(e), "trace": tb}
        print(f"Exception error: {result} e: {e}")
        await log_operation(db, "POST /", data.model_dump(), result)
        raise HTTPException(status_code=500, detail=result)

@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db_stock)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("/items", response_model=StocktakeItemSummaryResponse)
async def search_stocktake_items(
    session_id: Optional[UUID] = Query(None),
    stock_take_start_date: Optional[datetime] = Query(None),
    stock_take_end_date: Optional[datetime] = Query(None),
    upload_start_date: Optional[datetime] = Query(None),
    upload_end_date: Optional[datetime] = Query(None),
    location: Optional[str] = Query(None, description="按库位模糊查询"),
    barcode: Optional[str] = Query(None, description="按条码精确查询"),
    store: Optional[str] = Query(None, description="按门店过滤"),
    item_name: Optional[str] = Query(None, description="按中英文品名模糊查询"),
    creator_id: Optional[str] = Query(None, description="按创建人过滤"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=99999, description="每页数量"),
    db: AsyncSession = Depends(get_db_stock)
):
    # 条件列表
    session_conditions = []
    item_conditions = []

    if session_id:
        session_conditions.append(StocktakeItem.session_id == session_id)

    # 按 stock_take 时间筛选 StocktakeSession.timestamp
    if stock_take_start_date:
        session_conditions.append(StocktakeSession.timestamp >= stock_take_start_date)
    if stock_take_end_date:
        if stock_take_end_date.time() == datetime.min.time():
            stock_take_end_date = stock_take_end_date + timedelta(days=1) - timedelta(microseconds=1)
        session_conditions.append(StocktakeSession.timestamp <= stock_take_end_date)

    # 按 upload 时间筛选 StocktakeItem.create_time
    if upload_start_date:
        item_conditions.append(StocktakeItem.create_time >= upload_start_date)
    if upload_end_date:
        if upload_end_date.time() == datetime.min.time():
            upload_end_date = upload_end_date + timedelta(days=1) - timedelta(microseconds=1)
        item_conditions.append(StocktakeItem.create_time <= upload_end_date)

    if location:
        item_conditions.append(StocktakeItem.location.ilike(f"%{location}%"))
    if barcode:
        item_conditions.append(StocktakeItem.barcode.ilike(f"%{barcode}%"))
    if item_name:
        item_conditions.append(
            or_(
                ProductInfo.name_ch.ilike(f"%{item_name}%"),
                ProductInfo.name_en.ilike(f"%{item_name}%")
            )
        )
    if store:
        item_conditions.append(StocktakeItem.store == store)
    if creator_id:
        item_conditions.append(StocktakeItem.creator_id.ilike(f"%{creator_id}%"))

    # 主查询：StocktakeItem 联 StocktakeSession 和 ProductInfo
    stmt = (
        select(StocktakeItem, ProductInfo)
        .join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
        .outerjoin(ProductInfo, StocktakeItem.barcode == ProductInfo.barcode)
    )

    if session_conditions:
        stmt = stmt.where(and_(*session_conditions))
    if item_conditions:
        stmt = stmt.where(and_(*item_conditions))

    # 获取总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total = result_count.scalar() or 0

    # 分页
    stmt = stmt.order_by(StocktakeItem.create_time.desc()) \
               .offset((page - 1) * page_size) \
               .limit(page_size)

    result = await db.execute(stmt)
    rows = result.all()  # [(StocktakeItem, ProductInfo), ...]


    items_list = [
        StocktakeItemOut.model_validate({
            "id": item.id,
            "session_id": item.session_id,
            "location": item.location,
            "barcode": item.barcode,
            "name_ch": product.name_ch if product else None,
            "name_en": product.name_en if product else None,
            "price": product.price if product else None,
            "qty": item.qty,
            "time": item.time,
            "creator_id": item.creator_id,
            "modifier_id": item.modifier_id,
            "create_time": item.create_time,
            "update_time": item.update_time,
            "store": item.store
        })
        for item, product in rows
    ]

    logout = {
        "status": "success",
        "page": page,
        "page_size": page_size,
        "total": total,
        "items_count": len(items_list)
    }
    await log_operation(
        db,
        "get /items",
        {
            "session_id": session_id,
            "stock_take_start_date": stock_take_start_date,
            "stock_take_end_date": stock_take_end_date,
            "upload_start_date": upload_start_date,
            "upload_end_date": upload_end_date,
            "location": location,
            "barcode": barcode,
            "store": store,
            "item_name": item_name,
            "creator_id": creator_id, 
            "page": page,
            "page_size": page_size
        },
        logout
    )

    return StocktakeItemSummaryResponse(
        pickupItems=items_list,
        pagination=Pagination(
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if page_size else 1
        )
    )

@router.get("/items/v2", response_model=StocktakeItemSummaryResponseV2)
async def search_stocktake_items_v2(
    session_id: Optional[UUID] = Query(None),
    stock_take_start_date: Optional[datetime] = Query(None),
    stock_take_end_date: Optional[datetime] = Query(None),
    upload_start_date: Optional[datetime] = Query(None),
    upload_end_date: Optional[datetime] = Query(None),
    location: Optional[str] = Query(None, description="模糊匹配库位"),
    barcode: Optional[str] = Query(None, description="模糊匹配条码"),
    store: Optional[str] = Query(None, description="按门店过滤"),
    item_name: Optional[str] = Query(None, description="模糊匹配中英文名称"),
    creator_id: Optional[str] = Query(None, description="模糊匹配创建人"),
    duplicate: bool = Query(False, description="true: return all rows; false: keep last upload per location+barcode"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=99999, description="每页数量"),
    db: AsyncSession = Depends(get_db_stock)
):
    session_conditions = []
    item_conditions = [StocktakeItem.qty == 0]

    if session_id:
        session_conditions.append(StocktakeItem.session_id == session_id)

    if stock_take_start_date:
        session_conditions.append(StocktakeSession.timestamp >= stock_take_start_date)
    if stock_take_end_date:
        if stock_take_end_date.time() == datetime.min.time():
            stock_take_end_date = stock_take_end_date + timedelta(days=1) - timedelta(microseconds=1)
        session_conditions.append(StocktakeSession.timestamp <= stock_take_end_date)

    if upload_start_date:
        item_conditions.append(StocktakeItem.create_time >= upload_start_date)
    if upload_end_date:
        if upload_end_date.time() == datetime.min.time():
            upload_end_date = upload_end_date + timedelta(days=1) - timedelta(microseconds=1)
        item_conditions.append(StocktakeItem.create_time <= upload_end_date)

    if location:
        item_conditions.append(StocktakeItem.location.ilike(f"%{location}%"))
    if barcode:
        barcode_raw = barcode.strip()
        barcode_variants = {barcode_raw}
        barcode_stripped = barcode_raw.lstrip("0")
        if barcode_stripped:
            barcode_variants.add(barcode_stripped)
        barcode_conditions = [
            StocktakeItem.barcode.ilike(f"%{value}%")
            for value in barcode_variants
            if value
        ]
        if barcode_conditions:
            item_conditions.append(or_(*barcode_conditions))
    item_name_condition = None
    if item_name:
        item_name_condition = or_(
            ProductSnapshot.name_cn.ilike(f"%{item_name}%"),
            ProductSnapshot.name_en.ilike(f"%{item_name}%"),
        )
    if store:
        item_conditions.append(StocktakeItem.store == store)
    if creator_id:
        item_conditions.append(StocktakeItem.creator_id.ilike(f"%{creator_id}%"))

    item_order_col = StocktakeItem.create_time
    if duplicate:
        stmt = (
            select(StocktakeItem)
            .join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
        )
        if item_name_condition is not None:
            stmt = stmt.outerjoin(
                ProductSnapshot,
                or_(
                    ProductSnapshot.barcode == StocktakeItem.barcode,
                    ProductSnapshot.barcode == func.lpad(StocktakeItem.barcode, 14, "0"),
                ),
            )
        if session_conditions:
            stmt = stmt.where(and_(*session_conditions))
        if item_conditions:
            stmt = stmt.where(and_(*item_conditions))
        if item_name_condition is not None:
            stmt = stmt.where(item_name_condition)
    else:
        base_stmt = (
            select(
                StocktakeItem,
                func.row_number().over(
                    partition_by=(StocktakeItem.location, StocktakeItem.barcode),
                    order_by=(StocktakeItem.create_time.desc(), StocktakeItem.id.desc()),
                ).label("rn"),
            )
            .join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
        )
        if item_name_condition is not None:
            base_stmt = base_stmt.outerjoin(
                ProductSnapshot,
                or_(
                    ProductSnapshot.barcode == StocktakeItem.barcode,
                    ProductSnapshot.barcode == func.lpad(StocktakeItem.barcode, 14, "0"),
                ),
            )
        if session_conditions:
            base_stmt = base_stmt.where(and_(*session_conditions))
        if item_conditions:
            base_stmt = base_stmt.where(and_(*item_conditions))
        if item_name_condition is not None:
            base_stmt = base_stmt.where(item_name_condition)
        base_subq = base_stmt.subquery()
        item_alias = aliased(StocktakeItem, base_subq)
        item_order_col = item_alias.create_time
        stmt = select(item_alias).where(base_subq.c.rn == 1)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total = result_count.scalar() or 0

    stmt = stmt.order_by(item_order_col.desc()) \
               .offset((page - 1) * page_size) \
               .limit(page_size)

    result = await db.execute(stmt)
    #items = result.scalars().all()
    rows = result.all()

    items_list: List[StocktakeItemOutV2] = []

    snapshot_map: Dict[str, ProductSnapshot] = {}
    items = [r[0] for r in rows]
    if items:
        barcodes = {item.barcode.zfill(14) for item in items if item.barcode}
        if barcodes:
            snapshot_stmt = select(ProductSnapshot).where(ProductSnapshot.barcode.in_(barcodes))
            snapshot_result = await db.execute(snapshot_stmt)
            snapshot_map = {
                snapshot.barcode: snapshot
                for snapshot in snapshot_result.scalars().all()
            }

        for item in items:
            barcode_padded = item.barcode.zfill(14)
            snapshot = snapshot_map.get(barcode_padded)
            items_list.append(
                StocktakeItemOutV2.model_validate({
                    "id": item.id,
                    "session_id": item.session_id,
                    "location": item.location,
                    "barcode": barcode_padded,
                    "barcode_original": item.barcode,
                    "name_ch": snapshot.name_cn if snapshot else None,
                    "name_en": snapshot.name_en if snapshot else None,
                    "regular_price": snapshot.original_price if snapshot else None,
                    "active_price": snapshot.unit_price if snapshot else None,
                    "package_price": snapshot.pack_price if snapshot else None,
                    "package_count": snapshot.pack_qty if snapshot else None,
                    "tax": snapshot.tax if snapshot else None,
                    "specification": snapshot.specification if snapshot else None,
                    "unit_type": snapshot.unit_type if snapshot else None,
                    "qty": item.qty,
                    "time": item.time,
                    "creator_id": item.creator_id,
                    "modifier_id": item.modifier_id,
                    "create_time": item.create_time,
                    "update_time": item.update_time,
                    "image_url": get_image_url(barcode_padded),
                    "store": item.store
                })
            )

    logout = {
        "status": "success",
        "page": page,
        "page_size": page_size,
        "total": total,
        "items_count": len(items_list)
    }
    await log_operation(
        db,
        "get /items/v2",
        {
            "session_id": session_id,
            "stock_take_start_date": stock_take_start_date,
            "stock_take_end_date": stock_take_end_date,
            "upload_start_date": upload_start_date,
            "upload_end_date": upload_end_date,
            "location": location,
            "barcode": barcode,
            "store": store,
            "duplicate": duplicate,
            "item_name": item_name,
            "creator_id": creator_id,
            "page": page,
            "page_size": page_size
        },
        logout
    )

    return StocktakeItemSummaryResponseV2(
        pickupItems=items_list,
        pagination=Pagination(
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if page_size else 1
        )
    )

@router.get("", response_model=StocktakeSummaryResponse)
async  def search_stocktake(
    session_id: Optional[UUID] = Query(None),
    stock_take_start_date: Optional[datetime] = Query(None),
    stock_take_end_date: Optional[datetime] = Query(None),
    upload_start_date: Optional[datetime] = Query(None),
    upload_end_date: Optional[datetime] = Query(None),
    location: Optional[str] = Query(None, description="按库位模糊查询"),
    barcode: Optional[str] = Query(None, description="按条码精确查询"),
    store: Optional[str] = Query(None, description="按门店过滤"),
    item_name: Optional[str] = Query(None, description="按中英文品名模糊查询"),
    creator_id: Optional[str] = Query(None, description="按创建人过滤"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=99999, description="每页数量"),
    db: AsyncSession = Depends(get_db_stock)
):
    # 条件列表
    session_conditions = []
    item_conditions = []

    if session_id:
        session_conditions.append(StocktakeSession.id == session_id)
    if stock_take_start_date:
        session_conditions.append(StocktakeSession.timestamp >= stock_take_start_date)
    if stock_take_end_date:
        if stock_take_end_date.time() == datetime.min.time():
            stock_take_end_date = stock_take_end_date + timedelta(days=1) - timedelta(microseconds=1)
        session_conditions.append(StocktakeSession.timestamp <= stock_take_end_date)

    if upload_start_date:
        item_conditions.append(StocktakeItem.create_time >= upload_start_date)
    if upload_end_date:
        if upload_end_date.time() == datetime.min.time():
            upload_end_date = upload_end_date + timedelta(days=1) - timedelta(microseconds=1)
        item_conditions.append(StocktakeItem.create_time <= upload_end_date)

    if location:
        item_conditions.append(StocktakeItem.location.ilike(f"%{location}%"))
    if barcode:
        item_conditions.append(StocktakeItem.barcode.ilike(f"%{barcode}%"))
    if item_name:
        item_conditions.append(
            or_(
                ProductInfo.name_ch.ilike(f"%{item_name}%"),
                ProductInfo.name_en.ilike(f"%{item_name}%")
            )
        )
    if store:
        item_conditions.append(StocktakeItem.store == store)
    if creator_id:
        item_conditions.append(StocktakeItem.creator_id.ilike(f"%{creator_id}%"))

    # 主查询：StocktakeSession 联 StocktakeItem 和 ProductInfo
    stmt = (
        select(StocktakeSession, StocktakeItem, ProductInfo)
        .join(StocktakeItem, StocktakeSession.id == StocktakeItem.session_id)
        .outerjoin(ProductInfo, StocktakeItem.barcode == ProductInfo.barcode)
    )
    if session_conditions:
        stmt = stmt.where(and_(*session_conditions))
    if item_conditions:
        stmt = stmt.where(and_(*item_conditions))

    # 获取总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total = result_count.scalar() or 0

    # 分页
    stmt = stmt.order_by(StocktakeSession.timestamp.desc()) \
               .offset((page - 1) * page_size) \
               .limit(page_size)

    result = await db.execute(stmt)
    rows = result.all()  # 返回 [(StocktakeSession, StocktakeItem, ProductInfo), ...]

    # 聚合每个 session
    session_dict = {}
    for session, item, product in rows:
        # 只保留符合条件的 item
        session_id_str = str(session.id)
        if session_id_str not in session_dict:
            session_dict[session_id_str] = {
                "session": session,
                "items": []
            }
        session_dict[session_id_str]["items"].append(
            StocktakeItemOut.model_validate({
                "id": item.id,
                "session_id": item.session_id,
                "location": item.location,
                "barcode": item.barcode,
                "name_ch": product.name_ch if product else None,
                "name_en": product.name_en if product else None,
                "price": product.price if product else None,
                "qty": item.qty,
                "time": item.time,
                "creator_id": item.creator_id,
                "modifier_id": item.modifier_id,
                "create_time": item.create_time,
                "update_time": item.update_time,
                "store": item.store
            })
        )

    # 构造返回
    pickup_items = [
        StocktakeSessionWithItems.model_validate({
            **{"id": v["session"].id,
               "device_id": v["session"].device_id,
               "timestamp": v["session"].timestamp,
               "creator_id": v["session"].creator_id,
               "modifier_id": v["session"].modifier_id,
               "create_time": v["session"].create_time,
               "update_time": v["session"].update_time,
               "store": v["session"].store,
               "items": v["items"]}
        })
        for v in session_dict.values()
    ]

    return StocktakeSummaryResponse(
        pickupItems=pickup_items,
        pagination=Pagination(
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if page_size else 1
        )
    )

@router.get("/by-location", response_model=StockByLocationResponse)
async def get_stock_by_location(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    store: Optional[str] = Query(None, description="按门店过滤"),
    db: AsyncSession = Depends(get_db_stock)
):
    conditions = []
    if start_date:
        conditions.append(StocktakeItem.time >= start_date)
    if end_date:
        # 如果 end_date 没有时分秒，则添加 1 天再减 1 微秒，变成当日 23:59:59.999999
        if end_date.time() == datetime.min.time():
            end_date = end_date + timedelta(days=1) - timedelta(microseconds=1)
        conditions.append(StocktakeItem.time <= end_date)
    if store:
        conditions.append(StocktakeItem.store == store)

    #stmt = select(StocktakeItem)
    #stmt = select(StocktakeItem, ProductInfo).outerjoin(ProductInfo, StocktakeItem.barcode == ProductInfo.barcode)
    stmt = select(StocktakeItem, ProductInfo).join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id).outerjoin(ProductInfo, StocktakeItem.barcode == ProductInfo.barcode)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    items = result.all()

    location_data = defaultdict(list)
    for item, product in items:
        location_data[item.location].append({
            "session_id": str(item.session_id),
            "barcode": item.barcode,
            "name_ch": product.name_ch if product else None,
            "name_en": product.name_en if product else None,
            "price": product.price if product else None,
            "qty": item.qty,
            "time": item.time,
            "create_time": item.create_time,
            "creator_id": item.creator_id,
            "modifier_id": item.modifier_id,
            "store": item.store
        })
    logout = {"status": "success", "location_data": location_data}
    await log_operation(db, f"get /by-location", {"start_date": start_date, "end_date": end_date, "store": store}, logout)
    return location_data

@router.get("/by-location/v2", response_model=StockByLocationResponse)
async def get_stock_by_location_v2(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    location: Optional[str] = Query(None, description="模糊查询货架location"),
    store: Optional[str] = Query(None, description="按门店过滤"),
    duplicate: bool = Query(False, description="true: return all rows; false: keep last upload per location+barcode"),
    db: AsyncSession = Depends(get_db_stock)
):
    conditions = []
    if start_date:
        conditions.append(StocktakeItem.time >= start_date)
    if end_date:
        if end_date.time() == datetime.min.time():
            end_date = end_date + timedelta(days=1) - timedelta(microseconds=1)
        conditions.append(StocktakeItem.time <= end_date)
    if location:
        conditions.append(StocktakeItem.location.ilike(f"%{location}%"))
    if store:
        conditions.append(StocktakeItem.store == store)

    if duplicate:
        stmt = select(StocktakeItem).join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
        if conditions:
            stmt = stmt.where(and_(*conditions))
    else:
        base_stmt = select(
            StocktakeItem,
            func.row_number().over(
                partition_by=(StocktakeItem.location, StocktakeItem.barcode),
                order_by=(StocktakeItem.create_time.desc(), StocktakeItem.id.desc()),
            ).label("rn"),
        ).join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
        if conditions:
            base_stmt = base_stmt.where(and_(*conditions))
        base_subq = base_stmt.subquery()
        item_alias = aliased(StocktakeItem, base_subq)
        stmt = select(item_alias).where(base_subq.c.rn == 1)

    result = await db.execute(stmt)
    #items = result.scalars().all()
    rows = result.all()

    location_data = defaultdict(list)
    snapshot_map: Dict[str, ProductSnapshot] = {}
    items = [r[0] for r in rows]
    if items:
        barcodes = {item.barcode.zfill(14) for item in items if item.barcode}
        if barcodes:
            snapshot_stmt = select(ProductSnapshot).where(ProductSnapshot.barcode.in_(barcodes))
            snapshot_result = await db.execute(snapshot_stmt)
            snapshot_map = {
                snapshot.barcode: snapshot
                for snapshot in snapshot_result.scalars().all()
            }

    for item in items:
        barcode_padded = item.barcode.zfill(14)
        snapshot = snapshot_map.get(barcode_padded)
        image_url = get_image_url(barcode_padded)
        location_data[item.location].append({
            "session_id": str(item.session_id),
            "barcode": barcode_padded,
            "barcode_original": item.barcode,
            "name_ch": snapshot.name_cn if snapshot else None,
            "name_en": snapshot.name_en if snapshot else None,
            "price": snapshot.original_price if snapshot else None,
            "tax": snapshot.tax if snapshot else None,
            "specification": snapshot.specification if snapshot else None,
            "unit_type": snapshot.unit_type if snapshot else None,
            "qty": item.qty,
            "time": item.time,
            "create_time": item.create_time,
            "creator_id": item.creator_id,
            "modifier_id": item.modifier_id,
            "image_url": image_url,
            "store": item.store
        })
    logout = {"status": "success", "location_data": location_data}
    await log_operation(
        db,
        "get /by-location/v2",
        {"start_date": start_date, "end_date": end_date, "location": location, "store": store, "duplicate": duplicate},
        logout,
    )
    return location_data

@router.get("/by-location/export")
async def export_stock_by_location(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    store: Optional[str] = Query(None, description="按门店过滤"),
    db: AsyncSession = Depends(get_db_stock)
):
    conditions = []
    if start_date:
        conditions.append(StocktakeItem.time >= start_date)
    if end_date:
        # 如果 end_date 没有时分秒，则添加 1 天再减 1 微秒，变成当日 23:59:59.999999
        if end_date.time() == datetime.min.time():
            end_date = end_date + timedelta(days=1) - timedelta(microseconds=1)
        conditions.append(StocktakeItem.time <= end_date)
    if store:
        conditions.append(StocktakeItem.store == store)

    #stmt = select(StocktakeItem)
    stmt = select(StocktakeItem, ProductInfo).join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id).outerjoin(ProductInfo, StocktakeItem.barcode == ProductInfo.barcode)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No data found for the given time range.")

    data = [{
        "Store": item.store,
        "Location": item.location,
        "Barcode": item.barcode,
        "Name CH": product.name_ch if product else None,
        "Name EN": product.name_en if product else None,
        "Price": product.price if product else None,
        "Quantity": item.qty,
        "Stock Take Date": item.time.replace(tzinfo=None),         # 去掉时区
        "Upload Date": item.create_time.replace(tzinfo=None),  # 去掉时区
        "creator_id": item.creator_id,
        "modifier_id": item.modifier_id,
    } for item, product in rows]

    df = pd.DataFrame(data)
    df.sort_values(by=["Location", "Stock Take Date"], inplace=True)

    # ✅ 使用 tempfile 创建临时文件路径
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        file_path = tmp.name
        df.to_excel(file_path, index=False)
    logout = {"status": "success", "data": data}
    await log_operation(db, f"get /by-location/export", {"start_date": start_date, "end_date": end_date, "store": store}, logout)
    return FileResponse(
        path=file_path,
        filename="stock_by_location.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@router.get("/by-location/export/v2")
async def export_stock_by_location_v2(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    store: Optional[str] = Query(None, description="按门店过滤"),
    db: AsyncSession = Depends(get_db_stock)
):
    conditions = []
    if start_date:
        conditions.append(StocktakeItem.time >= start_date)
    if end_date:
        if end_date.time() == datetime.min.time():
            end_date = end_date + timedelta(days=1) - timedelta(microseconds=1)
        conditions.append(StocktakeItem.time <= end_date)
    if store:
        conditions.append(StocktakeItem.store == store)

    stmt = select(StocktakeItem).join(StocktakeSession, StocktakeItem.session_id == StocktakeSession.id)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    #items = result.scalars().all()
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No data found for the given time range.")

    snapshot_map: Dict[str, ProductSnapshot] = {}
    items = [r[0] for r in rows]
    barcodes = {item.barcode.zfill(14) for item in items if item.barcode}
    if barcodes:
        snapshot_stmt = select(ProductSnapshot).where(ProductSnapshot.barcode.in_(barcodes))
        snapshot_result = await db.execute(snapshot_stmt)
        snapshot_map = {
            snapshot.barcode: snapshot
            for snapshot in snapshot_result.scalars().all()
        }

    data = []
    for item in items:
        barcode_padded = item.barcode.zfill(14)
        snapshot = snapshot_map.get(barcode_padded)
        data.append({
            "Store": item.store,
            "Location": item.location,
            "Barcode": barcode_padded,
            "Barcode Original": item.barcode,
            "Name CH": snapshot.name_cn if snapshot else None,
            "Name EN": snapshot.name_en if snapshot else None,
            "Price": snapshot.original_price if snapshot else None,
            "Tax": snapshot.tax if snapshot else None,
            "Specification": snapshot.specification if snapshot else None,
            "Unit Type": snapshot.unit_type if snapshot else None,
            "Quantity": item.qty,
            "Stock Take Date": item.time.replace(tzinfo=None),
            "Upload Date": item.create_time.replace(tzinfo=None),
            "creator_id": item.creator_id,
            "modifier_id": item.modifier_id,
        })

    df = pd.DataFrame(data)
    df.sort_values(by=["Location", "Stock Take Date"], inplace=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        file_path = tmp.name
        df.to_excel(file_path, index=False)
    logout = {"status": "success", "data": data}
    await log_operation(db, "get /by-location/export/v2", {"start_date": start_date, "end_date": end_date, "store": store}, logout)
    return FileResponse(
        path=file_path,
        filename="stock_by_location_v2.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# -------------------- 下载模板 --------------------
@router.get("/product/template")
async def download_product_template():
    df = pd.DataFrame(columns=["barcode", "name_ch", "name_en", "price"])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        file_path = tmp.name
        df.to_excel(file_path, index=False)
    return FileResponse(file_path, filename="product_template.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -------------------- 上传产品信息 --------------------
@router.post("/product/upload")
async def upload_product_info(file: UploadFile = File(...), db: AsyncSession = Depends(get_db_stock)):
    try:
        df = pd.read_excel(file.file)
        if not {"barcode", "name_ch", "name_en", "price"}.issubset(df.columns):
            raise HTTPException(status_code=400, detail="Columns must include barcode, name_ch, name_en, price")

        for _, row in df.iterrows():
            barcode_str = str(row['barcode'])  # 强制转换为字符串
            name_ch = row.get("name_ch")
            name_en = row.get("name_en")
            price = row.get("price")
            if price is not None:
                try:
                    price = float(price)  # 强制转换
                except ValueError:
                    price = None  # 或者选择赋默认值 0.0
            else:
                price = None  # 或者 0.0

            if isinstance(name_ch, float) and math.isnan(name_ch):
                name_ch = None
            if isinstance(name_en, float) and math.isnan(name_en):
                name_en = None

            stmt = select(ProductInfo).where(ProductInfo.barcode == barcode_str)
            result = await db.execute(stmt)
            product = result.scalar_one_or_none()
            if product:
                product.name_ch = name_ch
                product.name_en = name_en
                product.price = price
            else:
                db.add(ProductInfo(barcode=barcode_str, name_ch=name_ch, name_en=name_en, price=price))
        await db.commit()
        return {"status": "success", "count": len(df)}

    except Exception as e:
        await db.rollback()
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{tb}")

@router.get("/product/list", response_model=ProductInfoResponse)
async def list_products(
    barcode: Optional[str] = Query(None, description="按条码模糊查询"),
    name: Optional[str] = Query(None, description="按中英文品名模糊查询"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(50, ge=1, le=99999, description="每页数量"),
    db: AsyncSession = Depends(get_db_stock)
):
    try:
        conditions = []
        if barcode:
            conditions.append(ProductInfo.barcode.ilike(f"%{barcode}%"))
        if name:
            conditions.append(
                or_(
                    ProductInfo.name_ch.ilike(f"%{name}%"),
                    ProductInfo.name_en.ilike(f"%{name}%")
                )
            )

        # 主查询
        stmt = select(ProductInfo)
        if conditions:
            stmt = stmt.where(*conditions)

        # 获取总数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        result_count = await db.execute(count_stmt)
        total = result_count.scalar() or 0

        # 分页查询
        stmt = stmt.order_by(ProductInfo.barcode.asc()) \
                   .offset((page - 1) * page_size) \
                   .limit(page_size)
        result = await db.execute(stmt)
        products = result.scalars().all()

        return ProductInfoResponse(
            products=[ProductInfoOut.model_validate(p) for p in products],
            pagination=Pagination(
                total=total,
                page=page,
                page_size=page_size,
                pages=ceil(total / page_size) if page_size else 1
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# 获取某个 session 的详细信息（含 items）
@router.get("/{session_id}", response_model=StocktakeSessionOut)
async def get_session_detail(session_id: UUID, db: AsyncSession = Depends(get_db_stock)):
    session_result = await db.execute(
        select(StocktakeSession).where(StocktakeSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    logout = {"status": "success", "session": session}
    await log_operation(db, f"get /{session_id}", {"session_id": session_id}, logout)
    return session

# 更新整个 session（先删除旧的 items，再插入新的）
@router.put("/{session_id}", response_model=StocktakeSessionOut)
async def update_session(
    session_data: StocktakeUpload,
    db: AsyncSession = Depends(get_db_stock),
):
    session_id = session_data.id
    # 查询 session
    session_result = await db.execute(
        select(StocktakeSession).where(StocktakeSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 删除旧的 items
    await db.execute(
        delete(StocktakeItem).where(StocktakeItem.session_id == session_id)
    )

    # 更新 session 元数据
    for field, value in session_data.model_dump(exclude_unset=True, exclude={"stocktake"}).items():
        setattr(session, field, value)
    session.update_time = datetime.now()

    # 插入新 items
    for item_data in session_data.stocktake:
        item_dict = item_data.model_dump()
        item_dict["session_id"] = session_id
        item_dict["store"] = item_data.store or session_data.store
        item = StocktakeItem(**item_dict)
        db.add(item)

    await db.commit()
    await db.refresh(session)
    logout = {"status": "success", "session": session}
    await log_operation(db, f"put /{session_id}", {"session_id": session_id}, logout)
    return session

# 删除整个 session（级联删除 items）
@router.delete("/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db_stock)):
    session_result = await db.execute(
        select(StocktakeSession).where(StocktakeSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 先删 items
    await db.execute(
        delete(StocktakeItem).where(StocktakeItem.session_id == session_id)
    )
    # 再删 session
    await db.execute(
        delete(StocktakeSession).where(StocktakeSession.id == session_id)
    )
    await db.commit()
    result = {"status": "deleted", "session_id": session_id}
    await log_operation(db, f"delete /{session_id}", {"session_id": session_id}, result)
    return result
