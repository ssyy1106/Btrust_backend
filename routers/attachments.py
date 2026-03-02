# routers/attachments.py （继续扩展）
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import os
from dependencies.permission import PermissionChecker
from crud import invoice as crud_invoice
from typing import Optional, List
from database import get_db
from models.invoice import InvoiceAttachment
from helper import verify_token, resolve_attachment_path
import httpx

router = APIRouter(
    prefix="/attachments",
    tags=["附件"]
)

async def get_store_by_attachment_id(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
) -> str:
    attachment = await crud_invoice.get_attachment(db, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if not attachment.invoice:
        raise HTTPException(status_code=404, detail="Associated invoice not found")

    return attachment.invoice.store  # 从 invoice 取 store

@router.get("/{attachment_id}")
async def get_attachment(
    attachment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    store: Optional[str] = Depends(get_store_by_attachment_id),  # 自动查出来store
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
    #user=Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this attachment."
        )
    # 查询附件
    result = await db.execute(
        select(InvoiceAttachment).where(InvoiceAttachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(status_code=404, detail="附件未找到")

    # 拼接完整路径
    file_path = resolve_attachment_path(attachment.path)
    # 检查文件是否存在
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=attachment.path)
    ORIGIN_SERVER_BASE_URL = "http://172.16.30.8:8000"
    a_url = f"{ORIGIN_SERVER_BASE_URL}/attachments/{attachment_id}"

    # 取原始 Authorization header
    auth_header = request.headers.get("authorization")

    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(a_url, headers=headers)

        if response.status_code == 200:
            return StreamingResponse(
                response.aiter_bytes(),
                media_type=response.headers.get("content-type"),
                headers={
                    "Content-Disposition": response.headers.get(
                        "content-disposition",
                        f'attachment; filename="{attachment.path}"'
                    )
                }
            )
    raise HTTPException(status_code=404, detail="文件不存在")

@router.get("/{attachment_id}/thumbnail")
async def get_attachment_thumbnail(
    attachment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    store: str = Depends(get_store_by_attachment_id),  # 自动查出来store
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
    #user=Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this thumbnail."
        )
    # 查数据库获取附件记录
    result = await db.execute(
        select(InvoiceAttachment).where(InvoiceAttachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(status_code=404, detail="附件未找到")

    # 构建缩略图路径
    thumbnail_path = resolve_attachment_path(attachment.thumbnail)

    # 检查文件是否存在
    if os.path.exists(thumbnail_path):
        return FileResponse(path=thumbnail_path, filename=attachment.thumbnail)
    ORIGIN_SERVER_BASE_URL = "http://172.16.30.8:8000"
    a_url = f"{ORIGIN_SERVER_BASE_URL}/attachments/{attachment_id}/thumbnail"

    # 取原始 Authorization header
    auth_header = request.headers.get("authorization")

    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(a_url, headers=headers)

        if response.status_code == 200:
            return StreamingResponse(
                response.aiter_bytes(),
                media_type=response.headers.get("content-type"),
                headers={
                    "Content-Disposition": response.headers.get(
                        "content-disposition",
                        f'attachment; filename="{attachment.thumbnail}"'
                    )
                }
            )
    raise HTTPException(status_code=404, detail="缩略图不存在")

