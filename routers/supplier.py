from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from schemas.invoice import SupplierCreate, SupplierOut
from crud import invoice as crud_supplier

router = APIRouter(prefix="/suppliers", tags=["Supplier"])

@router.post("/", response_model=SupplierOut)
async def create_supplier(supplier: SupplierCreate, db: AsyncSession = Depends(get_db)):
    return await crud_supplier.create_supplier(db, supplier)

@router.get("/", response_model=list[SupplierOut])
async def list_suppliers(db: AsyncSession = Depends(get_db)):
    return await crud_supplier.get_suppliers(db)