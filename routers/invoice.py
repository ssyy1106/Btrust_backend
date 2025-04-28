from fastapi import APIRouter, Depends, Query, HTTPException, File, UploadFile, Form
from datetime import date
import datetime
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from schemas.invoice import InvoiceCreate, InvoiceResponse, InvoiceOut, InvoiceOutFull, SupplierCreate, SupplierOut
from database import get_db
from crud import invoice as crud_invoice
from main import verify_token
from dependencies.permission import get_permission_checker
from models.invoice import Invoice, InvoiceAttachment, InvoiceDetail
import os
import shutil
import uuid
from io import BytesIO
from PIL import Image
from pydantic import TypeAdapter
import json

router = APIRouter(prefix="/invoices", tags=["Invoices"])

UPLOAD_DIR = "uploads/"
THUMBNAIL_DIR = "thumbnails/"
# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# @router.post("/")
# async def create(invoice: InvoiceCreate, db: AsyncSession = Depends(get_db), user=Depends(verify_token)):
#     return await crud_invoice.create_invoice(db, invoice, user)
@router.post("/", response_model=InvoiceOutFull)
async def create_invoice(
    supplier: int = Form(...),
    details: str = Form(...),
    store: str = Form(...),
    number: str = Form(...),
    totalamount: float= Form(...),
    invoicedate: date= Form(...),
    entrytime: date= Form(...),
    remark:str= Form(...),
    #department: int= Form(...),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    #user=Depends(verify_token)
    user = Depends(get_permission_checker(required_roles=["invoice:insert", "invoice:view"]))
):
    # 判断store参数是否正确
    if store not in user.store:
        raise HTTPException(status_code=404, detail="Store not found")
    suppliers = await crud_invoice.get_suppliers(db)
    if supplier not in [s.id for s in suppliers]:
        raise HTTPException(status_code=404, detail="Supplier not found")
    # 创建发票
    invoice = Invoice(
        number=number,
        totalamount=totalamount,
        invoicedate=invoicedate,
        supplierid=supplier,
        remark=remark,
        #department=department,
        createtime=datetime.datetime.now(),
        modifytime=datetime.datetime.now(),
        creatorid=int(user.id),
        modifierid=int(user.id),
        store = store,
        entrytime=entrytime
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    # 解析发票明细
    try:
        detail_items = json.loads(details)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON in 'details'")

    for idx, item in enumerate(detail_items):
        detail = InvoiceDetail(
            invoiceid=invoice.id,
            totalamount=item.get("totalamount"),
            department=item.get("department"),
            createtime=datetime.datetime.now(),
            modifytime=datetime.datetime.now(),
            creatorid=int(user.id),
            modifierid=int(user.id),
            status=0
        )
        db.add(detail)

    # 处理所有附件
    for idx, file in enumerate(files):
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        thumbnail_filepath = os.path.join(THUMBNAIL_DIR, f"thumb_{filename}")

        # 保存原始文件
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 生成缩略图
        try:
            with Image.open(filepath) as image:
                image.thumbnail((100, 100))
                image.save(thumbnail_filepath)
        except Exception as e:
            thumbnail_filepath = ""

        # 存数据库
        attachment = InvoiceAttachment(
            invoiceid=invoice.id,
            path=filepath,
            thumbnail=thumbnail_filepath,
            status=0,
            sort=idx + 1,
            createtime=datetime.datetime.now(),
            modifytime=datetime.datetime.now(),
            creatorid=int(user.id),
            modifierid=int(user.id)
        )
        db.add(attachment)

    await db.commit()

    # 刷新发票对象，加载附件关系
    await db.refresh(invoice)

    return invoice

# @router.get("/", response_model=List[InvoiceOutFull])
# async def list_invoices(start_date: Optional[date] = Query(None, description="start date"),
#     end_date: Optional[date] = Query(None, description="end date"),
#     db: AsyncSession = Depends(get_db), user=Depends(verify_token)):
#     return await crud_invoice.get_invoice_list(db, start_date, end_date)
@router.get("/", response_model=List[InvoiceOutFull])
async def list_invoices(
    invoice_start_date: Optional[date] = Query(None, description="发票开始日期"),
    invoice_end_date: Optional[date] = Query(None, description="发票结束日期"),
    entry_start_date: Optional[date] = Query(None, description="入账开始日期"),
    entry_end_date: Optional[date] = Query(None, description="入账结束日期"),
    number: Optional[str] = Query(None, description="发票号"),
    department: Optional[int] = Query(None, description="部门"),
    status: Optional[int] = Query(None, description="状态"),
    store: Optional[List[str]] = Query(None, description="门店（多个）"),
    supplier: Optional[List[int]] = Query(None, description="供应商ID（多个）"),
    db: AsyncSession = Depends(get_db),
    user = Depends(get_permission_checker(required_roles=["invoice:search", "invoice:view"]))
    #user=Depends(verify_token),
):
    return await crud_invoice.get_invoice_list(
        db=db,
        invoice_start_date=invoice_start_date,
        invoice_end_date=invoice_end_date,
        entry_start_date=entry_start_date,
        entry_end_date=entry_end_date,
        number=number,
        department=department,
        status=status,
        store=store,
        supplier=supplier,
    )

@router.get("/{invoice_id}", response_model=InvoiceOutFull)
async def get_invoice_by_id(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_permission_checker(required_roles=["invoice:search", "invoice:view"]))
):
    invoice = await crud_invoice.get_invoice_by_id(db, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice

# @router.post("/{invoice_id}/attachment")
# async def upload_attachment(
#     invoice_id: int,
#     attachment: UploadFile = File(...),
#     db: AsyncSession = Depends(get_db),
#     user=Depends(verify_token)
# ):
#     # 生成一个唯一的文件名
#     unique_filename = f"{uuid.uuid4().hex}_{attachment.filename}"
#     file_path = os.path.join(UPLOAD_DIR, unique_filename)

#     # 保存原始文件
#     with open(file_path, "wb") as buffer:
#         shutil.copyfileobj(attachment.file, buffer)

#     # 生成缩略图并保存
#     thumbnail_path = os.path.join(THUMBNAIL_DIR, f"thumb_{unique_filename}")
#     with Image.open(file_path) as img:
#         img.thumbnail((100, 100))  # 设置缩略图最大尺寸为 100x100
#         img.save(thumbnail_path)

#     # 在数据库中创建记录
#     invoice_attachment = InvoiceAttachment(
#         invoiceid=invoice_id,
#         status=1,  # 假设 1 表示有效状态
#         path=file_path,
#         thumbnail=thumbnail_path,
#         sort=1,  # 假设默认排序为 1
#         creatorid=int(user.id),
#         modifierid=int(user.id)
#     )

#     db.add(invoice_attachment)
#     await db.commit()

#     return {"message": "Attachment uploaded successfully", "file_path": file_path, "thumbnail_path": thumbnail_path}