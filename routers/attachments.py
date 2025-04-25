# routers/attachments.py （继续扩展）
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import os

from database import get_db
from models.invoice import InvoiceAttachment
from helper import verify_token, resolve_attachment_path

router = APIRouter(
    prefix="/attachments",
    tags=["附件"]
)

@router.get("/{attachment_id}")
async def get_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_token)
):
    # 查询附件
    result = await db.execute(
        select(InvoiceAttachment).where(InvoiceAttachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(status_code=404, detail="附件未找到")

    # 拼接完整路径
    file_path = resolve_attachment_path(attachment.path)
    print(file_path)
    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    # TODO: 你可以在这里根据 user 权限判断是否有访问该附件的权限

    return FileResponse(path=file_path, filename=attachment.path)

@router.get("/{attachment_id}/thumbnail")
async def get_attachment_thumbnail(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_token)
):
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
    if not os.path.exists(thumbnail_path):
        raise HTTPException(status_code=404, detail="缩略图不存在")

    # TODO: 可以根据 user 权限做限制，比如：
    # if not user.is_admin and attachment.owner_id != user.id:
    #     raise HTTPException(status_code=403, detail="无权访问该缩略图")

    return FileResponse(path=thumbnail_path, filename=attachment.thumbnail)
