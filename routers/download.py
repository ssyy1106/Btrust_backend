from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
import pandas as pd
import os
from hdbcli import dbapi
from helper import getHanaDB

router = APIRouter(prefix="/download", tags=["Download"])

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
