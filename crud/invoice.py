from sqlalchemy.ext.asyncio import AsyncSession
from models.invoice import Invoice, InvoiceDetail, Supplier
from schemas.invoice import InvoiceCreate, SupplierCreate
from sqlalchemy.future import select
from typing import Optional, List
from datetime import date
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, and_

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

# async def get_invoice_list(db: AsyncSession, start_date: Optional[date] = None, end_date: Optional[date] = None):
#     stmt = select(Invoice).options(
#         selectinload(Invoice.attachments),
#         selectinload(Invoice.details)
#     )
#     if start_date:
#         stmt = stmt.where(Invoice.invoicedate >= start_date)
#     if end_date:
#         stmt = stmt.where(Invoice.invoicedate <= end_date)

#     stmt = stmt.order_by(Invoice.invoicedate.desc())

#     result = await db.execute(stmt)
#     return result.scalars().all()
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
    if department is not None:
        stmt = stmt.where(Invoice.department == department)
    if status is not None:
        stmt = stmt.where(Invoice.status == status)
    if store:
        stmt = stmt.where(Invoice.store.in_(store))
    if supplier:
        stmt = stmt.where(Invoice.supplierid.in_(supplier))

    stmt = stmt.order_by(Invoice.invoicedate.desc())

    # result = await db.execute(stmt)
    # return result.scalars().all()
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    # 映射 supplier_name（如果你不使用自定义 Pydantic getter）
    for invoice in invoices:
        invoice.supplier_name = invoice.supplier.name if invoice.supplier else None

    return invoices

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
