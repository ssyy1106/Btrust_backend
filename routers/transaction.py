import datetime
from typing import Optional
import math
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from graphqlschema.schema import UserInformation
from helper import getDB, getStore, verify_token


router = APIRouter(prefix="/transaction", tags=["Transaction"])


def _validate_date(date_text: str) -> bool:
    try:
        datetime.date.fromisoformat(date_text)
        return True
    except ValueError:
        return False

def safe_float(value, default=0.0):
    if value is None:
        return default

    try:
        result = float(value)
    except (TypeError, ValueError, Decimal.InvalidOperation):
        return default

    if math.isnan(result) or math.isinf(result):
        return default

    return result

def _search_transactions_sync(
    store: str,
    date: str,
    transaction_begin_time: Optional[str],
    transaction_end_time: Optional[str],
    cashier_name: Optional[str],
    payment_type: Optional[str],
    amount_before_tax: Optional[float],
    amount_after_tax: Optional[float],
    transaction_id: Optional[str],
    pos_lane: Optional[str],
):
    sql = """
        SELECT
            t.date,
            t.store,
            t.transaction_begin_time,
            t.transaction_end_time,
            t.transaction_id,
            t.cashier_name,
            t.cashier_id,
            t.payment_type,
            t.amount_before_tax,
            t.amount_after_tax,
            t.total_tax,
            t.pos_lane,
            COALESCE(si.sale_item_count, 0) AS sale_item_count,
            COALESCE(si.sale_item_amount, 0) AS sale_item_amount,
            COALESCE(si.sale_item_discount, 0) AS sale_item_discount
        FROM transaction t
        LEFT JOIN (
            SELECT
                store,
                date,
                transaction_id,
                COUNT(*) AS sale_item_count,
                COALESCE(SUM(total_amount), 0) AS sale_item_amount,
                COALESCE(SUM(total_discount), 0) AS sale_item_discount
            FROM sale_item
            WHERE store = %s AND date = %s
            GROUP BY store, date, transaction_id
        ) si
            ON si.store = t.store
            AND si.date = t.date
            AND si.transaction_id = t.transaction_id
        WHERE t.store = %s AND t.date = %s
    """
    params = [store, date, store, date]

    if transaction_begin_time and transaction_end_time:
        sql += " AND t.transaction_begin_time BETWEEN %s AND %s"
        params.extend([transaction_begin_time, transaction_end_time])
    if cashier_name:
        sql += " AND t.cashier_name ILIKE %s"
        params.append(f"%{cashier_name}%")
    if payment_type:
        sql += " AND t.payment_type ILIKE %s"
        params.append(f"%{payment_type}%")
    if amount_before_tax is not None:
        sql += " AND t.amount_before_tax = %s"
        params.append(amount_before_tax)
    if amount_after_tax is not None:
        sql += " AND t.amount_after_tax = %s"
        params.append(amount_after_tax)
    if transaction_id:
        sql += " AND CAST(t.transaction_id AS TEXT) = %s"
        params.append(str(transaction_id))
    if pos_lane:
        sql += " AND CAST(t.pos_lane AS TEXT) = %s"
        params.append(str(pos_lane))

    sql += """
        ORDER BY
            t.transaction_begin_time DESC NULLS LAST,
            t.transaction_id DESC
    """

    with getDB() as conn:
        if not conn:
            raise HTTPException(status_code=503, detail="Unable to connect to sales database.")
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    details = []
    for row in rows:
        details.append(
            {
                "date": row[0],
                "store": row[1],
                "transaction_begin_time": row[2],
                "transaction_end_time": row[3],
                "transaction_id": row[4],
                "cashier_name": row[5],
                "cashier_id": row[6],
                "payment_type": row[7],
                "amount_before_tax": safe_float(row[8]),
                "amount_after_tax": safe_float(row[9]),
                "total_tax": safe_float(row[10]),
                "pos_lane": row[11],
                "sale_item_count": int(row[12] or 0),
                "sale_item_amount": safe_float(row[13]),
                "sale_item_discount": safe_float(row[14]),
            }
        )

    return {"items": len(details), "details": details}


def _search_transaction_items_sync(store: str, date: str, transaction_id: str):
    sql = """
        SELECT
            upc,
            weight,
            unit_price,
            total_amount,
            sub_department,
            department,
            total_discount,
            sales_qty
        FROM sale_item
        WHERE store = %s
          AND date = %s
          AND CAST(transaction_id AS TEXT) = %s
        ORDER BY upc
    """

    with getDB() as conn:
        if not conn:
            raise HTTPException(status_code=503, detail="Unable to connect to sales database.")
        with conn.cursor() as cursor:
            cursor.execute(sql, [store, date, transaction_id])
            rows = cursor.fetchall()

    details = []
    for row in rows:
        details.append(
            {
                "upc": row[0],
                "weight": row[1],
                "unit_price": safe_float(row[2]),
                "total_amount": safe_float(row[3]),
                "sub_department": row[4],
                "department": row[5],
                "total_discount": safe_float(row[6]),
                "sales_qty": row[7],
            }
        )

    return {"items": len(details), "details": details}


def _get_distinct_transaction_values_sync(store: str, date: str, field_name: str):
    allowed_fields = {"cashier_name", "pos_lane", "payment_type"}
    if field_name not in allowed_fields:
        raise HTTPException(status_code=400, detail="Invalid field.")

    sql = f"""
        SELECT DISTINCT {field_name}
        FROM transaction
        WHERE store = %s AND date = %s AND {field_name} IS NOT NULL
        ORDER BY {field_name}
    """

    with getDB() as conn:
        if not conn:
            raise HTTPException(status_code=503, detail="Unable to connect to sales database.")
        with conn.cursor() as cursor:
            cursor.execute(sql, [store, date])
            rows = cursor.fetchall()

    values = [row[0] for row in rows if row[0] not in (None, "")]
    return {"items": len(values), "details": values}


@router.get("/search")
async def search_transactions(
    store: str = Query(..., description="Store code, such as MT, NY, TE, MS, RH"),
    date: str = Query(..., description="Transaction date in YYYY-MM-DD format"),
    transaction_begin_time: Optional[str] = Query(None, description="transaction_begin_time range start"),
    transaction_end_time: Optional[str] = Query(None, description="transaction_begin_time range end"),
    cashier_name: Optional[str] = Query(None, description="Cashier name"),
    payment_type: Optional[str] = Query(None, description="Payment type"),
    amount_before_tax: Optional[float] = Query(None, description="Amount before tax"),
    amount_after_tax: Optional[float] = Query(None, description="Amount after tax"),
    transaction_id: Optional[str] = Query(None, description="Transaction ID"),
    pos_lane: Optional[str] = Query(None, description="POS lane"),
    user: UserInformation = Depends(verify_token),
):
    if store not in getStore():
        raise HTTPException(status_code=400, detail="Invalid store.")
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store.",
        )
    if not _validate_date(date):
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD format.")
    if (transaction_begin_time and not transaction_end_time) or (transaction_end_time and not transaction_begin_time):
        raise HTTPException(
            status_code=400,
            detail="transaction_begin_time and transaction_end_time must be provided together.",
        )

    return await run_in_threadpool(
        _search_transactions_sync,
        store,
        date,
        transaction_begin_time,
        transaction_end_time,
        cashier_name,
        payment_type,
        amount_before_tax,
        amount_after_tax,
        transaction_id,
        pos_lane,
    )


@router.get("/items/search")
async def search_transaction_items(
    store: str = Query(..., description="Store code, such as MT, NY, TE, MS, RH"),
    date: str = Query(..., description="Transaction date in YYYY-MM-DD format"),
    transaction_id: str = Query(..., description="Transaction ID"),
    user: UserInformation = Depends(verify_token),
):
    if store not in getStore():
        raise HTTPException(status_code=400, detail="Invalid store.")
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store.",
        )
    if not _validate_date(date):
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD format.")

    return await run_in_threadpool(_search_transaction_items_sync, store, date, transaction_id)


@router.get("/pos_lane")
async def get_transaction_pos_lanes(
    store: str = Query(..., description="Store code, such as MT, NY, TE, MS, RH"),
    date: str = Query(..., description="Transaction date in YYYY-MM-DD format"),
    user: UserInformation = Depends(verify_token),
):
    if store not in getStore():
        raise HTTPException(status_code=400, detail="Invalid store.")
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store.",
        )
    if not _validate_date(date):
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD format.")

    return await run_in_threadpool(_get_distinct_transaction_values_sync, store, date, "pos_lane")


@router.get("/cashier_name")
async def get_transaction_cashier_names(
    store: str = Query(..., description="Store code, such as MT, NY, TE, MS, RH"),
    date: str = Query(..., description="Transaction date in YYYY-MM-DD format"),
    user: UserInformation = Depends(verify_token),
):
    if store not in getStore():
        raise HTTPException(status_code=400, detail="Invalid store.")
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store.",
        )
    if not _validate_date(date):
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD format.")

    return await run_in_threadpool(_get_distinct_transaction_values_sync, store, date, "cashier_name")


@router.get("/payment_type")
async def get_transaction_payment_types(
    store: str = Query(..., description="Store code, such as MT, NY, TE, MS, RH"),
    date: str = Query(..., description="Transaction date in YYYY-MM-DD format"),
    user: UserInformation = Depends(verify_token),
):
    if store not in getStore():
        raise HTTPException(status_code=400, detail="Invalid store.")
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store.",
        )
    if not _validate_date(date):
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD format.")

    return await run_in_threadpool(_get_distinct_transaction_values_sync, store, date, "payment_type")
