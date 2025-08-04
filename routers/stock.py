from fastapi import FastAPI, HTTPException, Depends
from fastapi import APIRouter, Depends, Query, HTTPException, File, UploadFile, Form, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi.responses import JSONResponse
from datetime import datetime
from models.stock import OperateLog, StocktakeSession, StocktakeItem
from schemas.stock import (
    StocktakeSessionOut,
    StocktakeUpload,
    StocktakeItemOut, 
    StocktakeItemBase, 
    StocktakeSessionWithItems
)
from database import get_db_stock
import traceback
from typing import Optional, List
from fastapi.encoders import jsonable_encoder


router = APIRouter(prefix="/stock", tags=["Stock"])

# 用于记录操作日志
async def log_operation(db: AsyncSession, api_name: str, request_data, response_data):
    log = OperateLog(
        api_name=api_name,
        request_payload=jsonable_encoder(request_data),
        response_payload=jsonable_encoder(response_data),
        create_time=datetime.now()
    )
    db.add(log)
    await db.commit()


@router.post("/", response_model=StocktakeSessionOut)
async def upload_stocktake(data: StocktakeUpload, db: AsyncSession = Depends(get_db_stock)):
    try:
        now = datetime.now()
        session = StocktakeSession(
            device_id=data.deviceId,
            timestamp=data.timestamp,
            creator_id=0,
            modifier_id=0,
            create_time=now,
            update_time=now
        )
        db.add(session)
        await db.flush()  # 获取 session.id

        for item in data.stocktake:
            db_item = StocktakeItem(
                id=item.id,
                session_id=session.id,
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
        db.rollback()
        result = {"status": "error", "detail": "Duplicate ID or constraint violation", "info": str(e.orig)}
        await log_operation(db, "POST /", data.model_dump(), result)
        raise HTTPException(status_code=400, detail=result)

    except Exception as e:
        db.rollback()
        tb = traceback.format_exc()
        result = {"status": "error", "detail": str(e), "trace": tb}
        await log_operation(db, "POST /", data.model_dump(), result)
        raise HTTPException(status_code=500, detail=result)

@router.get("/", response_model=List[StocktakeSessionWithItems])
async  def search_stocktake(
    session_id: Optional[int] = Query(None),
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
        stmt = stmt.where(StocktakeSession.timestamp <= end_date)

    stmt = stmt.order_by(StocktakeSession.timestamp.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().unique().all()  # scalars() 用于解包 ORM 对象
    logout = {"status": "success", "sessions": sessions}
    await log_operation(db, f"get /", {"session_id": session_id, "start_date": start_date, "end_date": end_date}, logout)
    return sessions

# 获取某个 session 的详细信息（含 items）
@router.get("/{session_id}", response_model=StocktakeSessionOut)
async def get_session_detail(session_id: int, db: AsyncSession = Depends(get_db_stock)):
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
    session_id: int,
    session_data: StocktakeUpload,
    db: AsyncSession = Depends(get_db_stock),
):
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
    for field, value in session_data.model_dump(exclude_unset=True, exclude={"items"}).items():
        setattr(session, field, value)
    session.update_time = datetime.now()

    # 插入新 items
    for item_data in session_data.items:
        item = StocktakeItem(**item_data.model_dump(), session_id=session_id)
        item.create_time = item.update_time = datetime.now()
        db.add(item)

    await db.commit()
    await db.refresh(session)
    logout = {"status": "success", "session": session}
    await log_operation(db, f"put /{session_id}", {"session_id": session_id}, logout)
    return session

# 删除整个 session（级联删除 items）
@router.delete("/{session_id}")
async def delete_session(session_id: int, db: AsyncSession = Depends(get_db_stock)):
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