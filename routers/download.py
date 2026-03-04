from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from datetime import date, datetime
import pandas as pd
import os
from hdbcli import dbapi
from helper import getHanaDB, getDB, getStoreStr, get_config, getStore, getStores
from typing import Optional, List, Dict, Any
import psycopg2
import psycopg2.extras
from collections import defaultdict
import re
from pydantic import BaseModel

router = APIRouter(prefix="/download", tags=["Download"])


# 为 cashier_coupon 端点定义一个 Pydantic 模型。
class CouponCount(BaseModel):
    upc: str
    count: int
    value: float

class CashierCouponItem(BaseModel):
    """
    代表单个收银员的 coupon 销售数据。
    """
    cashier_id: str
    cashier_name: str
    tag: str  # 'confirm' or 'notconfirm'
    coupons: List[CouponCount]


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

from dependencies.permission import PermissionChecker

@router.get("/cashier_coupon", summary="获取收银员coupon销售统计", response_model=List[CashierCouponItem])
async def cashier_coupon(
    date: date,
    upc: List[str] = Query(..., description="一个包含3个coupon UPC的列表。"),
    store: str = Query(..., description="门店")
) -> List[CashierCouponItem]:
    """
    获取指定日期、门店和UPC的收银员销售统计。

    - **date**: 必填，查询的日期 (YYYY-MM-DD)。
    - **upc**: 必填，一个包含3个coupon UPC的列表。
    - **store**: 必填，单个门店代码。
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
    if not upcs or len(upcs) != 3:
        raise HTTPException(
            status_code=400,
            detail="请提供恰好3个coupon UPC。"
        )

    sorted_upcs = sorted(upcs)
    min_upc, mid_upc, max_upc = sorted_upcs[0], sorted_upcs[1], sorted_upcs[2]

    # 将 'nan' item 的负金额映射到对应的UPC及其面值
    amount_to_coupon_map = {
        -5.0:  {"upc": min_upc, "value": 5.0},
        -10.0: {"upc": mid_upc, "value": 10.0},
        -20.0: {"upc": max_upc, "value": 20.0},
    }
    valid_amounts = tuple(amount_to_coupon_map.keys())

    # 2. 校验门店权限
    valid_stores_list = getStore()
    if store not in valid_stores_list:
        raise HTTPException(status_code=400, detail=f"无效的门店: {store}")
    store_filter_str = f"('{store}')"

    # 3. 动态构建SQL查询
    sql_query = f"""
        WITH valid_transactions AS (
            SELECT DISTINCT transaction_id, store, date
            FROM sale_item
            WHERE
                date = %s
                AND store IN {store_filter_str}
                AND upc IN %s
        )
        SELECT
            t.cashier_id,
            t.store,
            t.cashier_name,
            s.total_amount,
            t.transaction_id
        FROM
            transaction t
        JOIN
            sale_item s ON t.transaction_id = s.transaction_id AND t.store = s.store AND t.date = s.date
        JOIN
            valid_transactions vt ON t.transaction_id = vt.transaction_id AND t.store = vt.store AND t.date = vt.date
        WHERE
            t.date = %s
          AND t.store IN {store_filter_str}
          AND s.upc = 'nan'
          AND s.total_amount IN %s
    """

    # 4. 执行查询
    conn = None
    try:
        conn = getDB()
        if not conn:
            raise HTTPException(status_code=503, detail="无法建立数据库连接。")
        
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(sql_query, (date, tuple(upcs), date, valid_amounts))
            rows = cursor.fetchall()

        if not rows:
            return []

        # 5. 处理结果，按收银员统计coupon数量
        # 首先按 transaction_id 分组
        transactions_map = defaultdict(list)
        for row in rows:
            transactions_map[row['transaction_id']].append(row)

        cashier_coupon_counts = defaultdict(lambda: defaultdict(int))
        cashier_name_map = {}
        cashier_tags = defaultdict(lambda: 'confirm') # 默认所有收银员都是 confirm

        for transaction_id, items in transactions_map.items():
            cashier_id = str(items[0]['cashier_id'])
            cashier_name = items[0]['cashier_name']
            cashier_name_map[cashier_id] = cashier_name

            # 检查一个 transaction 中是否有多个不同的 coupon 金额
            amounts_in_tx = {float(item['total_amount']) for item in items}
            
            # 如果有歧义（多于一个不同的coupon金额），将该收银员标记为 notconfirm
            if len(amounts_in_tx.intersection(valid_amounts)) > 1:
                cashier_tags[cashier_id] = 'notconfirm'
                # 即使不确定，也继续统计，但前端可以根据 tag 决定如何展示

            # 正常统计
            for item in items:
                amount = float(item['total_amount'])
                coupon_info = amount_to_coupon_map.get(amount)
                if coupon_info:
                    effective_upc = coupon_info["upc"]
                    cashier_coupon_counts[cashier_id][effective_upc] += 1


        # 6. 格式化最终响应
        response_list = []
        for cashier_id, counts in cashier_coupon_counts.items():
            coupon_list = []
            for u in sorted_upcs:
                coupon_value = 0.0
                for info in amount_to_coupon_map.values():
                    if info["upc"] == u:
                        coupon_value = info["value"]
                        break
                
                coupon_list.append(CouponCount(
                    upc=u,
                    count=counts.get(u, 0),
                    value=coupon_value
                ))

            response_list.append(
                CashierCouponItem(
                    cashier_id=cashier_id,
                    cashier_name=cashier_name_map.get(cashier_id, "Unknown"),
                    tag=cashier_tags[cashier_id],
                    coupons=coupon_list
                )
            )

        return sorted(response_list, key=lambda x: x.cashier_name)

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发生意外错误: {str(e)}")
    finally:
        if conn:
            conn.close()
