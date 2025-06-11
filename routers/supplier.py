from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from database import get_db
from schemas.invoice import SupplierCreate, SupplierOut
from crud import invoice as crud_supplier
from dependencies.permission import PermissionChecker

router = APIRouter(prefix="/suppliers", tags=["Supplier"])

@router.post("/", response_model=SupplierOut)
#async def create_supplier(supplier: SupplierCreate, db: AsyncSession = Depends(get_db), user = Depends(PermissionChecker(required_roles=["invoice:insert", "invoice:view"]))):
async def create_supplier(supplier: SupplierCreate, db: AsyncSession = Depends(get_db)):
    try:
        # 调用crud_supplier创建供应商
        return await crud_supplier.create_supplier(db, supplier)
    except IntegrityError as e:
        # 捕获唯一约束错误并返回 409 错误
        if "unique_supplier_name" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Supplier with this name already exists"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred"
            )
    #return await crud_supplier.create_supplier(db, supplier)

@router.get("/", response_model=list[SupplierOut])
async def list_suppliers(db: AsyncSession = Depends(get_db)):
    return await crud_supplier.get_suppliers(db)