from fastapi import FastAPI, HTTPException, Depends
from fastapi import APIRouter, Depends, Query, HTTPException, File, UploadFile, Form, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from fastapi.responses import JSONResponse, FileResponse
from datetime import datetime, timedelta
from models.stock import OperateLog, StocktakeSession, StocktakeItem
from schemas.stock import (
    StocktakeSessionOut,
    StocktakeUpload,
    StocktakeItemOut, 
    StocktakeItemBase, 
    StocktakeSessionWithItems,
    StockByLocationResponse
)
from collections import defaultdict
from database import get_db_stock
import traceback
from typing import Optional, List, Dict, Any
from fastapi.encoders import jsonable_encoder
from uuid import UUID
from helper import log_and_save
import pandas as pd
import os
import tempfile


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


@router.post("/", response_model=StocktakeSessionOut)
async def upload_stocktake(data: StocktakeUpload, db: AsyncSession = Depends(get_db_stock)):
    try:
        session_id = data.id

        # 删除旧记录
        await db.execute(delete(StocktakeItem).where(StocktakeItem.session_id == session_id))
        await db.execute(delete(StocktakeSession).where(StocktakeSession.id == session_id))
        now = datetime.now()
        session = StocktakeSession(
            id=session_id,
            device_id=data.deviceId,
            timestamp=data.timestamp,
            creator_id=0,
            modifier_id=0,
            create_time=now,
            update_time=now
        )
        db.add(session)

        for item in data.stocktake:
            db_item = StocktakeItem(
                id=item.id,
                session_id=session_id,
                location=item.location,
                barcode=item.barcode,
                qty=item.qty,
                time=item.time,
                creator_id=0,
                modifier_id=0,
                create_time=now,
                update_time=now
            )
            db.add(db_item)

        await db.commit()
        await db.refresh(session)

        result = {"status": "success", "session_id": session.id}
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

@router.get("/", response_model=List[StocktakeSessionWithItems])
async  def search_stocktake(
    session_id: Optional[UUID] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db_stock)
):
    stmt = select(StocktakeSession).options(selectinload(StocktakeSession.items))

    if session_id:
        stmt = stmt.where(StocktakeSession.id == session_id)
    if start_date:
        stmt = stmt.where(StocktakeSession.timestamp >= start_date)
    if end_date:
        # 如果 end_date 没有时分秒，则添加 1 天再减 1 微秒，变成当日 23:59:59.999999
        if end_date.time() == datetime.min.time():
            end_date = end_date + timedelta(days=1) - timedelta(microseconds=1)
        stmt = stmt.where(StocktakeSession.timestamp <= end_date)

    stmt = stmt.order_by(StocktakeSession.timestamp.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().unique().all()  # scalars() 用于解包 ORM 对象
    logout = {"status": "success", "sessions": sessions}
    await log_operation(db, f"get /", {"session_id": session_id, "start_date": start_date, "end_date": end_date}, logout)
    return sessions

@router.get("/by-location", response_model=StockByLocationResponse)
async def get_stock_by_location(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
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

    stmt = select(StocktakeItem)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    items = result.scalars().all()

    location_data = defaultdict(list)
    for item in items:
        location_data[item.location].append({
            "session_id": str(item.session_id),
            "barcode": item.barcode,
            "qty": item.qty,
            "time": item.time,
            "create_time": item.create_time,
        })
    logout = {"status": "success", "location_data": location_data}
    await log_operation(db, f"get /by-location", {"start_date": start_date, "end_date": end_date}, logout)
    return location_data

@router.get("/by-location/export")
async def export_stock_by_location(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
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

    stmt = select(StocktakeItem)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    items = result.scalars().all()

    if not items:
        raise HTTPException(status_code=404, detail="No data found for the given time range.")

    data = [{
        "Location": item.location,
        "Barcode": item.barcode,
        "Quantity": item.qty,
        "Stock Take Date": item.time.replace(tzinfo=None),         # 去掉时区
        # "Session ID": str(item.session_id),
        "Upload Date": item.create_time.replace(tzinfo=None),  # 去掉时区
    } for item in items]

    df = pd.DataFrame(data)
    df.sort_values(by=["Location", "Item Time"], inplace=True)

    # ✅ 使用 tempfile 创建临时文件路径
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        file_path = tmp.name
        df.to_excel(file_path, index=False)
    logout = {"status": "success", "data": data}
    await log_operation(db, f"get /by-location/export", {"start_date": start_date, "end_date": end_date}, logout)
    return FileResponse(
        path=file_path,
        filename="stock_by_location.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

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


