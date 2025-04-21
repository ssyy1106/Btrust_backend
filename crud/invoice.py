from sqlalchemy.ext.asyncio import AsyncSession
from models.invoice import Invoice, InvoiceDetail
from schemas.invoice import InvoiceCreate
from sqlalchemy.future import select
from typing import Optional
from datetime import date

async def create_invoice(db: AsyncSession, invoice: InvoiceCreate):
    print(invoice)
    db_invoice = Invoice(
        number=invoice.number,
        totalamount=invoice.totalamount,
        remark=invoice.remark,
        invoicedate=invoice.invoicedate,
        entrytime=invoice.entrytime,
        department=invoice.department,
        creatorid=invoice.creatorid
    )
    for detail in invoice.details:
        db_invoice.details.append(
            InvoiceDetail(
                totalamount=detail.totalamount,
                department=detail.department,
                creatorid=invoice.creatorid
            )
        )
    db.add(db_invoice)
    await db.commit()
    await db.refresh(db_invoice)
    return db_invoice

async def get_invoice_list(db: AsyncSession, start_date: Optional[date] = None, end_date: Optional[date] = None):
    stmt = select(Invoice)
    if start_date:
        stmt = stmt.where(Invoice.invoicedate >= start_date)
    if end_date:
        stmt = stmt.where(Invoice.invoicedate <= end_date)

    stmt = stmt.order_by(Invoice.invoicedate.desc())

    result = await db.execute(stmt)
    return result.scalars().all()
