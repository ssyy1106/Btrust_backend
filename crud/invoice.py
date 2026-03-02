from sqlalchemy.ext.asyncio import AsyncSession
from models.invoice import Invoice, InvoiceDetail, Supplier, InvoiceAttachment
from schemas.invoice import InvoiceCreate, SupplierCreate
from sqlalchemy.future import select
from typing import Optional, List
from datetime import date
from sqlalchemy.orm import selectinload, aliased
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

# async def get_invoice_list(
#     db: AsyncSession,
#     invoice_start_date: Optional[date] = None,
#     invoice_end_date: Optional[date] = None,
#     entry_start_date: Optional[date] = None,
#     entry_end_date: Optional[date] = None,
#     number: Optional[str] = None,
#     department: Optional[int] = None,
#     status: Optional[int] = None,
#     store: Optional[List[str]] = None,
#     supplier: Optional[List[int]] = None,
#     page: int = 1,
#     page_size: int = 20,
#     sort_by: Optional[str] = "invoicedate",
#     sort_dir: str = "desc",

# ):
#     stmt = select(Invoice).options(
#         selectinload(Invoice.attachments),
#         selectinload(Invoice.details),
#         selectinload(Invoice.supplier),
#     )

#     if invoice_start_date:
#         stmt = stmt.where(Invoice.invoicedate >= invoice_start_date)
#     if invoice_end_date:
#         stmt = stmt.where(Invoice.invoicedate <= invoice_end_date)
#     if entry_start_date:
#         stmt = stmt.where(Invoice.entrytime >= entry_start_date)
#     if entry_end_date:
#         stmt = stmt.where(Invoice.entrytime <= entry_end_date)
#     if number:
#         stmt = stmt.where(Invoice.number.like(f"%{number}%"))
#     if status is not None:
#         stmt = stmt.where(Invoice.status == status)
#     if store:
#         stmt = stmt.where(Invoice.store.in_(store))
#     if supplier:
#         stmt = stmt.where(Invoice.supplierid.in_(supplier))

#     SupplierAlias = aliased(Supplier)
#     # 排序字段白名单
#     order_fields = {
#         "number": Invoice.number,
#         "invoicedate": Invoice.invoicedate,
#         "entrytime": Invoice.entrytime,
#         "createtime": Invoice.createtime,
#         "suppliername": SupplierAlias.name,
#         "store": Invoice.store,
#         "totalamount": Invoice.totalamount,
#         "status": Invoice.status,
#         "department_total_amount": None  # Python层排序
#     }

#     if sort_by == "suppliername":
#         stmt = stmt.join(SupplierAlias, Invoice.supplier).order_by(
#             SupplierAlias.name.desc() if sort_dir == "desc" else SupplierAlias.name.asc()
#         )
#     elif sort_by in order_fields and order_fields[sort_by] is not None:
#         order_column = order_fields[sort_by]
#         stmt = stmt.order_by(order_column.desc() if sort_dir == "desc" else order_column.asc())
#     else:
#         stmt = stmt.order_by(Invoice.invoicedate.desc())  # 默认

#     result = await db.execute(stmt)
#     invoices = result.scalars().unique().all()
#     total_amount = sum(inv.totalamount or 0 for inv in invoices)
#     # 部门筛选逻辑：仅返回包含该部门的 invoice（可选）
#     if department is not None:
#         invoices = [inv for inv in invoices if any(d.department == department for d in inv.details)]
#         for inv in invoices:
#             inv.department_total_amount = sum(
#                 (d.totalamount or 0) for d in inv.details if d.department == department
#             )
#         total_department_amount = sum(inv.department_total_amount or 0 for inv in invoices)
#     else:
#         for inv in invoices:
#             inv.department_total_amount = None
#         total_department_amount = 0

#     # Python层排序（仅限 department_total_amount）
#     if sort_by == "department_total_amount":
#         invoices.sort(
#             key=lambda inv: inv.department_total_amount or 0,
#             reverse=(sort_dir == "desc")
#         )

#     # 分页处理
#     start = (page - 1) * page_size
#     end = start + page_size
#     total = len(invoices)
#     return {
#         "total": total,
#         "items": invoices[start:end],
#         "total_amount": total_amount,
#         "total_department_amount": total_department_amount
#     }

async def get_invoice_list(
    db: AsyncSession,
    invoice_start_date=None,
    invoice_end_date=None,
    entry_start_date=None,
    entry_end_date=None,
    number=None,
    department=None,
    status=None,
    store=None,
    supplier=None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "invoicedate",
    sort_dir: str = "desc",
):

    SupplierAlias = aliased(Supplier)

    # ----------------------------
    # 基础查询
    # ----------------------------
    stmt = select(Invoice)

    # 条件
    conditions = []

    if invoice_start_date:
        conditions.append(Invoice.invoicedate >= invoice_start_date)
    if invoice_end_date:
        conditions.append(Invoice.invoicedate <= invoice_end_date)
    if entry_start_date:
        conditions.append(Invoice.entrytime >= entry_start_date)
    if entry_end_date:
        conditions.append(Invoice.entrytime <= entry_end_date)
    if number:
        conditions.append(Invoice.number.ilike(f"%{number}%"))
    if status is not None:
        conditions.append(Invoice.status == status)
    if store:
        conditions.append(Invoice.store.in_(store))
    if supplier:
        conditions.append(Invoice.supplierid.in_(supplier))

    if conditions:
        stmt = stmt.where(and_(*conditions))

    # ----------------------------
    # 部门过滤（SQL层）
    # ----------------------------
    if department is not None:
        stmt = stmt.join(Invoice.details).where(
            InvoiceDetail.department == department
        )

    # ----------------------------
    # 排序
    # ----------------------------
    order_map = {
        "number": Invoice.number,
        "invoicedate": Invoice.invoicedate,
        "entrytime": Invoice.entrytime,
        "createtime": Invoice.createtime,
        "store": Invoice.store,
        "totalamount": Invoice.totalamount,
        "status": Invoice.status,
    }

    if sort_by == "suppliername":
        stmt = stmt.join(SupplierAlias, Invoice.supplier)
        order_column = SupplierAlias.name
    elif sort_by in order_map:
        order_column = order_map[sort_by]
    else:
        order_column = Invoice.invoicedate

    if sort_dir == "desc":
        stmt = stmt.order_by(order_column.desc())
    else:
        stmt = stmt.order_by(order_column.asc())

    # ----------------------------
    # 统计 total 数量
    # ----------------------------
    count_stmt = select(func.count(func.distinct(Invoice.id)))

    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))

    if department is not None:
        count_stmt = count_stmt.join(Invoice.details).where(
            InvoiceDetail.department == department
        )

    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # ----------------------------
    # 分页
    # ----------------------------
    stmt = stmt.options(
        selectinload(Invoice.attachments),
        selectinload(Invoice.details),
        selectinload(Invoice.supplier),
    )

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    invoices = result.scalars().unique().all()

    # ----------------------------
    # 汇总金额（SQL层）
    # ----------------------------
    total_amount_stmt = select(func.sum(Invoice.totalamount))

    if conditions:
        total_amount_stmt = total_amount_stmt.where(and_(*conditions))

    total_amount_result = await db.execute(total_amount_stmt)
    total_amount = total_amount_result.scalar() or 0

    # ----------------------------
    # 部门金额统计
    # ----------------------------
    total_department_amount = 0

    if department is not None:
        dept_sum_stmt = select(
            func.sum(InvoiceDetail.totalamount)
        ).join(Invoice).where(
            InvoiceDetail.department == department
        )

        if conditions:
            dept_sum_stmt = dept_sum_stmt.where(and_(*conditions))

        dept_result = await db.execute(dept_sum_stmt)
        total_department_amount = dept_result.scalar() or 0

    return {
        "total": total,
        "items": invoices,
        "total_amount": total_amount,
        "total_department_amount": total_department_amount
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
