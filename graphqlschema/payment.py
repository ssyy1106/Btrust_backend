import datetime
from contextlib import aclosing
from decimal import Decimal

from sqlalchemy import text

from database import get_db_store_sqlserver_factory
from helper import getPaymentTypes, getStore, getPaymentTypeStr
from graphqlschema.schema import (
    DatePaymentData, DatePaymentSummary, DatePaymentDetail,
    DatePaymentSearchParameter, MonthPaymentSearchParameter,
    MonthPaymentData, MonthPaymentSummary, MonthPaymentDetail,
)


def check_store_payment(stores, paymentType) -> bool:
    if not stores or not paymentType:
        return False
    if stores != ['ALL'] and not all(store in getStore() for store in stores):
        return False
    if paymentType != ['ALL'] and not all(pm in getPaymentTypes() for pm in paymentType):
        return False
    return True


def check_payment_date(param: DatePaymentSearchParameter) -> bool:
    if param.FromDate > param.ToDate:
        return False
    return check_store_payment(param.Store, param.PaymentType)


def check_payment_month(param: MonthPaymentSearchParameter) -> bool:
    try:
        from_month = datetime.datetime.strptime(param.FromMonth, '%Y-%m')
        to_month = datetime.datetime.strptime(param.ToMonth, '%Y-%m')
    except (TypeError, ValueError):
        return False
    if from_month > to_month:
        return False
    return check_store_payment(param.Store, param.PaymentType)


def _payment_type(raw_type, configured_types):
    name = (raw_type or '').strip()
    if name.casefold().startswith('drwr '):
        name = name[5:].strip()
    elif name.casefold().startswith('dwr '):
        name = name[4:].strip()
    # Match configured names anywhere in the description, preferring
    # the most specific configured name so each amount is counted once.
    for payment in sorted(configured_types, key=len, reverse=True):
        if payment.casefold() in name.casefold():
            return payment
    return 'other'


async def _get_payment_amounts(stores, payment_types, from_date, to_date, monthly=False):
    selected_stores = getStore() if stores == ['ALL'] else stores
    all_types, selected_types = getPaymentTypeStr(payment_types)
    configured_types = getPaymentTypes()
    period = 'CONVERT(char(7), f.F254, 120)' if monthly else 'CAST(f.F254 AS date)'
    query = text(f"""
        SELECT {period} AS period, t.F1039 AS paymenttype,
               SUM(f.F65) AS amount
        FROM dbo.RPT_FIN f
        LEFT JOIN dbo.TLZ_TAB t ON f.F1034 = t.F1034
        WHERE f.F1031 = 'D'
          AND f.F1034 BETWEEN 1200 AND 1299
          AND f.F254 >= :from_date AND f.F254 < :to_date
        GROUP BY {period}, t.F1039
        ORDER BY period, t.F1039
    """)
    amounts = {}
    for store in dict.fromkeys(selected_stores):
        dependency = get_db_store_sqlserver_factory(store)
        async with aclosing(dependency()) as sessions:
            async for db in sessions:
                result = await db.execute(query, {'from_date': from_date, 'to_date': to_date})
                for period_value, raw_type, amount in result.all():
                    payment = _payment_type(raw_type, configured_types)
                    if all_types:
                        amounts.setdefault((period_value, store, 'other'), Decimal(0))
                    elif payment not in selected_types:
                        continue
                    key = (period_value, store, payment)
                    amounts[key] = amounts.get(key, Decimal(0)) + (amount or Decimal(0))
    return amounts


async def getPaymentDateData(param: DatePaymentSearchParameter) -> DatePaymentData:
    amounts = await _get_payment_amounts(
        param.Store, param.PaymentType, param.FromDate,
        param.ToDate + datetime.timedelta(days=1),
    )
    details = [
        DatePaymentDetail(
            amountbeforetax=float(amount), amountaftertax=float(amount),
            transactions=0, paymenttype=payment, store=store, date=period,
        )
        for (period, store, payment), amount in sorted(amounts.items())
    ]
    total = float(sum(amounts.values()))
    return DatePaymentData(
        summary=DatePaymentSummary(
            items=len(details), totalamountbeforetax=total, totalamountaftertax=total,
        ),
        details=details,
    )


async def getPaymentMonthData(param: MonthPaymentSearchParameter) -> MonthPaymentData:
    from_date = datetime.datetime.strptime(param.FromMonth, '%Y-%m').date()
    last_month = datetime.datetime.strptime(param.ToMonth, '%Y-%m').date()
    to_date = (last_month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    amounts = await _get_payment_amounts(
        param.Store, param.PaymentType, from_date, to_date, monthly=True,
    )
    details = [
        MonthPaymentDetail(
            amountbeforetax=float(amount), amountaftertax=float(amount),
            transactions=0, paymenttype=payment, store=store, month=period,
        )
        for (period, store, payment), amount in sorted(amounts.items())
    ]
    total = float(sum(amounts.values()))
    return MonthPaymentData(
        summary=MonthPaymentSummary(
            items=len(details), totalamountbeforetax=total, totalamountaftertax=total,
        ),
        details=details,
    )
