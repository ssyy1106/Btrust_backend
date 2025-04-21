from fastapi import APIRouter, Depends, Query
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.invoice import InvoiceCreate
from database import get_db
from crud import invoice as crud_invoice
from main import verify_token

router = APIRouter(prefix="/invoices", tags=["Invoices"])

@router.post("/")
async def create(invoice: InvoiceCreate, db: AsyncSession = Depends(get_db), user=Depends(verify_token)):
    return await crud_invoice.create_invoice(db, invoice)

@router.get("/")
async def list_invoices(start_date: Optional[date] = Query(None, description="start date"),
    end_date: Optional[date] = Query(None, description="end date"),
    db: AsyncSession = Depends(get_db), user=Depends(verify_token)):
    return await crud_invoice.get_invoice_list(db, start_date, end_date)
