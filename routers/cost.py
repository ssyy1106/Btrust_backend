from fastapi import APIRouter, UploadFile, HTTPException, Depends, File
import pandas as pd
from fastapi.responses import StreamingResponse
import io
import csv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from dependencies.permission import PermissionChecker
from models.cost import CostImport  # 你的模型文件
from database import get_db_cost
import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from io import BytesIO
from helper import getStore
from graphqlschema.department import getDepartments

router = APIRouter(prefix="/costs", tags=["Cost"])
BASE_DIR = Path(__file__).parent.parent  # 退一级
UPLOAD_DIR = BASE_DIR / "uploads" / "costs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.get("/template", summary="下载成本录入模板（含限制）")
async def download_cost_template(
    user=Depends(PermissionChecker(required_roles=["cost:download"])),
    db: AsyncSession = Depends(get_db_cost),
):
    valid_stores = getStore()
    valid_departments = [item.name["en_us"] for item in getDepartments(None).departments]

    # ✅ 创建工作簿
    wb = Workbook()

    # ✅ 先创建 Data sheet
    ws_data = wb.active
    ws_data.title = "Data"
    ws_data.append(["store", "department", "month", "cost"])

    # ✅ 创建 Reference sheet
    ws_ref = wb.create_sheet(title="Reference")

    # 写入门店
    ws_ref.append(["Store"])
    for store in valid_stores:
        ws_ref.append([store])
    ws_ref.append([])  # 空行
    ws_ref.append(["Department"])
    for dept in valid_departments:
        ws_ref.append([dept])
    ws_ref.column_dimensions['A'].hidden = True

    # ✅ 定义数据有效性范围
    # store 开始范围：Reference!A2:A(n+1)
    store_start_row = 2
    store_end_row = store_start_row + len(valid_stores) - 1
    store_range = f"Reference!A{store_start_row}:A{store_end_row}"
    # department 开始范围：Reference!A(len(valid_stores)+4) 到末尾
    dept_start_row = len(valid_stores) + 4
    dept_end_row = dept_start_row + len(valid_departments) - 1
    dept_range = f"Reference!A{dept_start_row}:A{dept_end_row}"

    # ✅ 创建数据验证对象
    store_validation = DataValidation(
        type="list",
        formula1=store_range,
        allow_blank=True,
        showErrorMessage=True,
        errorTitle='无效门店',
        error='请从下拉列表中选择有效门店',
    )
    dept_validation = DataValidation(
        type="list",
        formula1=dept_range,
        allow_blank=True,
        showErrorMessage=True,
        errorTitle='无效部门',
        error='请从下拉列表中选择有效部门',
    )
    ws_data.add_data_validation(store_validation)
    ws_data.add_data_validation(dept_validation)

    # ✅ 把验证应用到每一行
    for row in range(2, 500):  # 500 行范围
        store_validation.add(ws_data[f"A{row}"])
        dept_validation.add(ws_data[f"B{row}"])

    # ✅ 输出成字节流
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cost_template.xlsx"},
    )

@router.post("/upload", summary="上传成本 Excel 文件")
async def upload_cost_xlsx(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_cost),
    user=Depends(PermissionChecker(required_roles=["cost:insert"])),
):
    # ✅ 检查扩展名
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 xlsx 文件")

    contents = await file.read()

    # ✅ 用 openpyxl 加载工作簿
    try:
        wb = load_workbook(BytesIO(contents), data_only=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法读取文件: {e}")

    # ✅ 获取 Data sheet
    if "Data" not in wb.sheetnames:
        raise HTTPException(status_code=400, detail="缺少 Data sheet")
    ws = wb["Data"]

    # ✅ 获取标题行并检查必需列
    header = [str(cell.value).strip().lower() for cell in next(ws.iter_rows(max_row=1))]
    required_cols = {"store", "department", "month", "cost"}
    if not required_cols.issubset(header):
        raise HTTPException(status_code=400, detail=f"缺少必须列: {required_cols}")

    col_idx = {name: header.index(name) for name in header}
    valid_stores = getStore()
    valid_departments = [item.name["en_us"] for item in getDepartments(None).departments]

    # ✅ 遍历数据行
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        store = str(row[col_idx["store"]]).strip() if row[col_idx["store"]] is not None else None
        dept = str(row[col_idx["department"]]).strip() if row[col_idx["department"]] is not None else None
        # month = str(row[col_idx["month"]]).strip() if row[col_idx["month"]] is not None else None
        month_cell = row[col_idx["month"]]
        if isinstance(month_cell, (datetime.date, datetime.datetime)):
            month = month_cell.strftime("%Y-%m")
        else:
            month = str(month_cell)[:7]
        cost = row[col_idx["cost"]]

        if not store or not dept or not month or cost is None:
            continue  # 跳过空行

        if store not in valid_stores:
            raise HTTPException(status_code=400, detail=f"第{i}行: {store} 不是有效门店")
        if dept not in valid_departments:
            raise HTTPException(status_code=400, detail=f"第{i}行: {dept} 不是有效部门")

        try:
            cost = float(cost)
        except Exception:
            raise HTTPException(status_code=400, detail=f"第{i}行: cost 值无效 '{row[col_idx['cost']]}'")

        # ✅ 判断数据库中是否有相同记录
        stmt = select(CostImport).where(
            CostImport.store == store,
            CostImport.department == dept,
            CostImport.month == month,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.cost = cost
            existing.updated_at = datetime.datetime.now()
        else:
            new_record = CostImport(
                store=store,
                department=dept,
                month=month,
                cost=cost,
                created_at=datetime.datetime.now(),
                updated_at=datetime.datetime.now(),
            )
            db.add(new_record)

    await db.commit()

    # ✅ 持久化原始上传文件
    filename = f"{datetime.datetime.now():%Y%m%d%H%M%S}_{file.filename}"
    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(contents)

    return {"message": "导入完成并已更新现有记录", "saved_file": str(file_path)}
