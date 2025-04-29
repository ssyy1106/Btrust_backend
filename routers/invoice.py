from fastapi import APIRouter, Depends, Query, HTTPException, File, UploadFile, Form, status
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
from dependencies.permission import PermissionChecker
from models.invoice import Invoice, InvoiceAttachment, InvoiceDetail
import os
import shutil
import uuid
from io import BytesIO
from PIL import Image
from pydantic import TypeAdapter
import json
from helper import getStores

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
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
):
    # 判断store参数是否正确
    if store not in user.store:
        raise HTTPException(status_code=403, detail="No permission for this store")
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
    user: dict = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
    #user=Depends(verify_token),
):
    store = getStores(user, store)
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
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
    #user = Depends(get_permission_checker(required_roles=["invoice:search", "invoice:view"]))
):
    invoice = await crud_invoice.get_invoice_by_id(db, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access these invoices."
        )
    return invoice

@router.put("/{invoice_id}", response_model=InvoiceOutFull)
async def update_invoice(
    status: int,
    invoice_id: int,
    supplier: int = Form(...),
    details: str = Form(...),
    store: str = Form(...),
    number: str = Form(...),
    totalamount: float = Form(...),
    invoicedate: date = Form(...),
    entrytime: date = Form(...),
    remark: str = Form(...),
    files: List[UploadFile] = File([]),
    keep_attachment_ids: List[int] = Form([]),
    db: AsyncSession = Depends(get_db),
    user = Depends(PermissionChecker(required_roles=["invoice:update", "invoice:view"]))
):
    # 获取并验证发票
    #stmt = select(Invoice).where(Invoice.id == invoice_id)
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(
            selectinload(Invoice.attachments)
        )
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if store not in user.store:
        raise HTTPException(status_code=403, detail="No permission for this store")
    suppliers = await crud_invoice.get_suppliers(db)
    if supplier not in [s.id for s in suppliers]:
        raise HTTPException(status_code=404, detail="Supplier not found")
    
    # 更新基本字段
    invoice.status = status
    invoice.supplierid = supplier
    #invoice.details = details
    invoice.store = store
    invoice.number = number
    invoice.totalamount = totalamount
    invoice.invoicedate = invoicedate
    invoice.entrytime = entrytime
    invoice.remark = remark
    invoice.modifytime = datetime.datetime.now()
    invoice.modifierid = int(user.id)
    # ---------- 处理 InvoiceDetail ----------
    try:
        parsed_details = json.loads(details)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in 'details'")
    stmt = select(InvoiceDetail).where(InvoiceDetail.invoiceid == invoice_id)
    result = await db.execute(stmt)
    existing_details = result.scalars().all()
    existing_detail_map = {d.id: d for d in existing_details}
    incoming_ids = set()
    for item in parsed_details:
        detail_id = item.get("id")
        if detail_id and detail_id in existing_detail_map:
            # 修改现有明细
            detail = existing_detail_map[detail_id]
            detail.totalamount = item.get("totalamount", 0)
            detail.department = item.get("department")
            detail.modifytime = datetime.datetime.now()
            detail.modifierid = int(user.id)
            incoming_ids.add(detail_id)
        else:
            # 新增明细
            new_detail = InvoiceDetail(
                invoiceid=invoice.id,
                totalamount=item.get("totalamount"),
                department=item.get("department"),
                createtime=datetime.datetime.now(),
                modifytime=datetime.datetime.now(),
                creatorid=int(user.id),
                modifierid=int(user.id),
                status=0
            )
            db.add(new_detail)
    # 删除未包含的明细
    for detail in existing_details:
        if detail.id not in incoming_ids:
            await db.delete(detail)
    #await db.commit()

    # 删除未保留的旧附件
    for att in invoice.attachments:
        if att.id not in keep_attachment_ids:
            if os.path.exists(att.path):
                os.remove(att.path)
            if att.thumbnail and os.path.exists(att.thumbnail):
                os.remove(att.thumbnail)
            await db.delete(att)

    # 添加新附件
    for idx, file in enumerate(files):
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        thumbnail_filepath = os.path.join(THUMBNAIL_DIR, f"thumb_{filename}")
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        try:
            with Image.open(filepath) as image:
                image.thumbnail((100, 100))
                image.save(thumbnail_filepath)
        except Exception:
            thumbnail_filepath = ""

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
    await db.refresh(invoice)
    return invoice