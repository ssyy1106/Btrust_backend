from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from datetime import date, datetime
import pandas as pd
import os
from hdbcli import dbapi
from helper import getHanaDB, getDB, getStoreStr, get_config, getStore
from typing import Optional, List, Dict, Any
import psycopg2
import psycopg2.extras
import re
from pydantic import BaseModel

router = APIRouter(prefix="/download", tags=["Download"])


# 为 cashier_coupon 端点定义一个 Pydantic 模型。
# 这有助于生成更清晰的 API 文档，并提供更好的类型检查。
class CashierCouponItem(BaseModel):
    """
    代表单个收银员的 coupon 销售数据。
    除了以下固定字段，还会包含动态生成的 upc 统计字段，例如 'upc_00960000000219'。
    """
    store: str
    cashier_name: str
    cashier_id: str

    class Config:
        # 允许动态字段（例如 upc_...）存在于模型中
        extra = "allow"

def get_hana_connection():
    try:
        conn, schema = getHanaDB()
        if not conn:
            raise HTTPException(status_code=500, detail=f"HANA connect failed: {str(e)}")
        cursor = conn.cursor()
        return conn, cursor, schema
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HANA connect failed: {str(e)}")

def fetch_hana_stock(cursor, schema):
    sqlstr = f"""
        SELECT 
                OITM."CodeBars" AS "BarCode",
                X."DistNumber" AS "BatchNumber",
                MAX(X."Quantity" - X."QuantOut") AS "BatchQuantity", -- 件数
                MAX(
                    CASE 
                        WHEN ITBA_INNER."AttributeValue" IS NULL 
                            OR ITBA_INNER."AttributeValue" = '' 
                            OR TO_BIGINT(ITBA_INNER."AttributeValue") = 0
                        THEN 0
                        ELSE FLOOR((X."Quantity" - X."QuantOut") / TO_BIGINT(ITBA_INNER."AttributeValue"))
                    END
                ) AS "BatchQuantity", -- 箱数
                MAX(
                    CASE 
                        WHEN ITBA_INNER."AttributeValue" IS NULL 
                            OR ITBA_INNER."AttributeValue" = '' 
                            OR TO_BIGINT(ITBA_INNER."AttributeValue") = 0
                            OR X."CostTotal" = 0 
                            OR X."Quantity" = 0
                        THEN 0
                        ELSE TO_DECIMAL(X."CostTotal"/X."Quantity" * TO_DECIMAL(ITBA_INNER."AttributeValue", 8, 2), 8, 2)
                    END
                ) AS "CostPerCase",
                MAX(TO_BIGINT(ITBA_INNER."AttributeValue")) AS "UnitsPerCase", -- 每箱件数
                OITM."ItemCode",
                OPDN."CardCode" AS "VendorCode",
                OPDN."CardName" AS "VendorName",
                MAX(OITM."OnHand") AS "ItemTotalQty"    -- 总件数 暂时不用
            FROM SBO_BTRUST_LIVE.PMX_INVT 
            INNER JOIN SBO_BTRUST_LIVE.OITM 
                ON PMX_INVT."ItemCode" = OITM."ItemCode" 
            INNER JOIN SBO_BTRUST_LIVE.PMX_ITRI 
                ON PMX_INVT."ItemTransactionalInfoKey" = PMX_ITRI."InternalKey" 
            INNER JOIN SBO_BTRUST_LIVE.PDN1 
                ON OITM."ItemCode" = PDN1."ItemCode" 
            INNER JOIN SBO_BTRUST_LIVE.OPDN 
                ON PDN1."DocEntry" = OPDN."DocEntry" 
            INNER JOIN SBO_BTRUST_LIVE.PMX_INVD 
                ON OPDN."ObjType" = PMX_INVD."TransType" 
                AND PDN1."DocEntry" = PMX_INVD."DocEntry" 
                AND PDN1."LineNum" = PMX_INVD."DocLineNum" 
                AND PMX_INVD."ItemTransactionalInfoKey" = PMX_INVT."ItemTransactionalInfoKey" 
            LEFT JOIN SBO_BTRUST_LIVE.OBTN X 
                ON X."DistNumber" = PMX_ITRI."BatchNumber" 
                AND X."ItemCode" = PMX_ITRI."ItemCode" 
            LEFT JOIN SBO_BTRUST_LIVE.PMX_ITBA ITBA_INNER 
                ON ITBA_INNER."BatchAttributeCode" = 'INNER_PACK' 
                AND ITBA_INNER."ItriKey" = PMX_ITRI."InternalKey" 
            LEFT JOIN SBO_BTRUST_LIVE.OITB 
                ON OITB."ItmsGrpCod" = OITM."ItmsGrpCod"
            GROUP BY 
                OITM."CodeBars",
                X."DistNumber",
                OITM."ItemCode",
                OPDN."CardCode",
                OPDN."CardName"
    """
    cursor.execute(sqlstr)
    res = cursor.fetchall()
    # 转 dict
    dic_hana_barcode_stock = {}
    for stock in res:
        # key = (item_code, batch_number)
        dic_hana_barcode_stock[(stock[6], stock[1])] = {
            "QuantityUnits": stock[2],  # 件数 ItemTotalQty
            "QuantityCase": stock[3],  # 箱数 BatchQuantity
            "CostPerCase": stock[4],  # CostPerCase
            "VendorCode": stock[7],  # VendorCode
            "VendorName": stock[8], # VendorName
            "UnitsPerCase": stock[5],  # UnitsPerCase 每箱件数
        }
    return dic_hana_barcode_stock

@router.get("/sap-stock/export", summary="导出SAP库存Excel")
async def export_sap_stock():
    conn, cursor, schema = get_hana_connection()
    try:
        dic_hana_stock = fetch_hana_stock(cursor, schema)
        if not dic_hana_stock:
            raise HTTPException(status_code=404, detail="No stock data found in SAP")

        # 转 DataFrame
        df = pd.DataFrame([
            {
                "ItemCode": item_code,
                "BatchNumber": batch_number,
                **values
            }
            for (item_code, batch_number), values in dic_hana_stock.items()
        ])

        export_dir = os.path.join(os.getcwd(), "tmp")
        os.makedirs(export_dir, exist_ok=True)

        filepath = os.path.join(export_dir, "export.xlsx")
        # filename = f"sap_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        # filepath = os.path.join("/tmp", filename)
        df.to_excel(filepath, index=False, engine='openpyxl')

        return FileResponse(filepath, filename="export.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@router.get("/cashier_coupon", summary="获取收银员coupon销售统计", response_model=List[CashierCouponItem])
async def cashier_coupon(
    date: date,
    store: Optional[List[str]] = Query(None),
    upc: Optional[List[str]] = Query(None)
) -> List[CashierCouponItem]:
    """
    获取指定日期、门店和UPC的收银员销售统计。

    - **date**: 必填，查询的日期 (YYYY-MM-DD)。
    - **store**: 可选，门店列表。如果不提供，则查询所有门店。
    - **upc**: 可选，UPC列表。如果不提供，则从配置文件 `config.ini` 的 `[Coupon]` 部分读取 `upc` 字段。
    """
    # 1. 如果未提供upc，则从配置文件读取
    if not upc:
        try:
            config = get_config()
            upc_str = config.get('Coupon', 'upc', fallback=None)
            if not upc_str:
                raise HTTPException(status_code=404, detail="在配置文件中未找到 [Coupon] -> upc 的默认设置。")
            upcs = [u.strip() for u in upc_str.split(',')]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取配置时出错: {e}")
    else:
        upcs = upc

    if not upcs:
        return []

    # 2. 验证并准备门店过滤字符串
    store_list = store or ["ALL"]
    if "ALL" not in store_list:
        valid_stores = getStore()
        for s in store_list:
            if s not in valid_stores:
                raise HTTPException(status_code=400, detail=f"无效的门店: {s}")
    
    store_filter_str = getStoreStr(store_list)

    # 3. 动态构建SQL查询
    def sanitize_alias(s: str) -> str:
        # 将非字母数字字符替换为下划线，以创建安全的列别名
        return re.sub(r'[^a-zA-Z0-9]', '_', s)

    count_filters = [
        f"COUNT(*) FILTER (WHERE s.upc = %s) AS upc_{sanitize_alias(u)}"
        for u in upcs
    ]
    
    sql_query = f"""
        SELECT
            t.store,
            t.cashier_name,
            t.cashier_id,
            {', '.join(count_filters)}
        FROM transaction t
        INNER JOIN sale_item s ON t.transaction_id = s.transaction_id AND t.store = s.store AND t.date = s.date
        WHERE t.date = %s
          AND t.store IN {store_filter_str}
          AND s.upc IN %s
        GROUP BY t.store,t.cashier_name, t.cashier_id
        ORDER BY t.cashier_name;
    """

    # 4. 执行查询
    conn = None
    try:
        conn = getDB()
        if not conn:
            raise HTTPException(status_code=503, detail="无法建立数据库连接。")
        
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            params = upcs + [date, tuple(upcs)]
            cursor.execute(sql_query, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发生意外错误: {str(e)}")
    finally:
        if conn:
            conn.close()
