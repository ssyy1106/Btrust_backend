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

router = APIRouter(prefix="/costs", tags=["Cost"])
BASE_DIR = Path(__file__).parent.parent  # 退一级
UPLOAD_DIR = BASE_DIR / "uploads" / "costs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# UPLOAD_DIR = Path(__file__).parent / "uploads" / "costs"
# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.get("/template", summary="下载成本导入模板")
async def download_cost_template(
    user = Depends(PermissionChecker(required_roles=["cost:download"]))
):
    # CSV header
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["store", "department", "month", "cost"])  # 模板列
    output.seek(0)
    return StreamingResponse(
        output, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cost_template.csv"}
    )

@router.post("/upload", summary="上传成本 CSV 文件")
async def upload_cost_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_cost),
    user = Depends(PermissionChecker(required_roles=["cost:insert"]))
):
    # 只接受 CSV
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    required_cols = {"store", "department", "month", "cost"}
    if not required_cols.issubset(reader.fieldnames or []):
        raise HTTPException(
            status_code=400,
            detail=f"缺少必须列: {required_cols}"
        )

    for i, row in enumerate(reader, 1):
        store = row.get("store")
        dept = row.get("department")
        month = row.get("month")
        try:
            cost = float(row.get("cost"))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"第 {i} 行 cost 值无效: {row.get('cost')}"
            )

        # 判断数据库中是否有相同记录
        stmt = select(CostImport).where(
            CostImport.store == store,
            CostImport.department == dept,
            CostImport.month == month,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # 更新
            existing.cost = cost
            existing.updated_at = datetime.datetime.now()
        else:
            # 新增
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

    # 持久化原始上传文件（时间戳前缀防重名）
    filename = f"{datetime.datetime.now():%Y%m%d%H%M%S}_{file.filename}"
    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(contents)

    return {"message": "导入完成并已更新现有记录", "saved_file": str(file_path)}
