from sqlalchemy.ext.asyncio import AsyncSession
from models.invoice import Invoice, InvoiceDetail, Supplier, InvoiceAttachment
from schemas.invoice import InvoiceCreate, SupplierCreate
from sqlalchemy.future import select
from typing import Optional, List
from datetime import date
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, and_, exists, select, desc, asc, func

async def get_attachment(db: AsyncSession, attachment_id: int) -> InvoiceAttachment:
    stmt = (
        select(InvoiceAttachment)
        .options(selectinload(InvoiceAttachment.invoice))  # 自动加载关联的 Invoice
        .where(InvoiceAttachment.id == attachment_id)
    )
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    return attachment

async def create_invoice(db: AsyncSession, invoice: InvoiceCreate, user):
    db_invoice = Invoice(
        number=invoice.number,
        totalamount=invoice.totalamount,
        remark=invoice.remark,
        invoicedate=invoice.invoicedate,
        entrytime=invoice.entrytime,
        department=invoice.department,
        supplier = invoice.supplier,
        #creatorid=invoice.creatorid
        creatorid=int(user.id),
        modifierid = int(user.id)
    )
    for detail in invoice.details:
        db_invoice.details.append(
            InvoiceDetail(
                totalamount=detail.totalamount,
                department=detail.department,
                creatorid=int(user.id),
                modifierid = int(user.id)
            )
        )
    db.add(db_invoice)
    await db.commit()
    await db.refresh(db_invoice)
    return db_invoice

async def get_invoice_list(
    db: AsyncSession,
    invoice_start_date: Optional[date] = None,
    invoice_end_date: Optional[date] = None,
    entry_start_date: Optional[date] = None,
    entry_end_date: Optional[date] = None,
    number: Optional[str] = None,
    department: Optional[int] = None,
    status: Optional[int] = None,
    store: Optional[List[str]] = None,
    supplier: Optional[List[int]] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Optional[str] = "invoicedate",
    sort_dir: str = "desc",

):
    stmt = select(Invoice).options(
        selectinload(Invoice.attachments),
        selectinload(Invoice.details),
        selectinload(Invoice.supplier),
    )

    if invoice_start_date:
        stmt = stmt.where(Invoice.invoicedate >= invoice_start_date)
    if invoice_end_date:
        stmt = stmt.where(Invoice.invoicedate <= invoice_end_date)
    if entry_start_date:
        stmt = stmt.where(Invoice.entrytime >= entry_start_date)
    if entry_end_date:
        stmt = stmt.where(Invoice.entrytime <= entry_end_date)
    if number:
        stmt = stmt.where(Invoice.number.like(f"%{number}%"))
    if status is not None:
        stmt = stmt.where(Invoice.status == status)
    if store:
        stmt = stmt.where(Invoice.store.in_(store))
    if supplier:
        stmt = stmt.where(Invoice.supplierid.in_(supplier))

    # 排序字段白名单
    order_fields = {
        "number": Invoice.number,
        "invoicedate": Invoice.invoicedate,
        "entrytime": Invoice.entrytime,
        "supplierid": Invoice.supplierid,
        "store": Invoice.store,
        "totalamount": Invoice.totalamount,
        "status": Invoice.status,
        "department_total_amount": None  # Python层排序
    }
    # SQL排序（如果不是department_total_amount）
    if sort_by in order_fields and order_fields[sort_by] is not None:
        order_column = order_fields[sort_by]
        stmt = stmt.order_by(order_column.desc() if sort_dir == "desc" else order_column.asc())
    else:
        stmt = stmt.order_by(Invoice.invoicedate.desc())  # 默认

    result = await db.execute(stmt)
    invoices = result.scalars().unique().all()
    # 部门筛选逻辑：仅返回包含该部门的 invoice（可选）
    if department is not None:
        invoices = [inv for inv in invoices if any(d.department == department for d in inv.details)]
        for inv in invoices:
            inv.department_total_amount = sum(
                (d.totalamount or 0) for d in inv.details if d.department == department
            )
    else:
        for inv in invoices:
            inv.department_total_amount = None

    # Python层排序（仅限 department_total_amount）
    if sort_by == "department_total_amount":
        invoices.sort(
            key=lambda inv: inv.department_total_amount or 0,
            reverse=(sort_dir == "desc")
        )

    # 分页处理
    start = (page - 1) * page_size
    end = start + page_size
    total = len(invoices)
    return {
        "total": total,
        "items": invoices[start:end]
    }

# 根据发票ID查询发票
async def get_invoice_by_id(db: AsyncSession, invoice_id: int):
    stmt = select(Invoice).where(Invoice.id == invoice_id).options(
        selectinload(Invoice.attachments),
        selectinload(Invoice.details)
    )
    result = await db.execute(stmt)
    return result.scalars().first()

    result = await db.execute(select(Invoice).filter(Invoice.id == invoice_id))
    return result.scalar_one_or_none()  # 返回单个发票或 None

async def create_supplier(db: AsyncSession, supplier_data: SupplierCreate):
    new_supplier = Supplier(**supplier_data.dict())
    db.add(new_supplier)
    await db.commit()
    await db.refresh(new_supplier)
    return new_supplier

async def get_suppliers(db: AsyncSession):
    result = await db.execute(select(Supplier).order_by(Supplier.id.desc()))
    return result.scalars().all()
