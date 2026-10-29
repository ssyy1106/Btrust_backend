from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from graphqlschema import payment
from graphqlschema.schema import DatePaymentSearchParameter, MonthPaymentSearchParameter


@pytest.fixture
def store_db(monkeypatch):
    monkeypatch.setattr(payment, 'getStore', lambda: ['MS', 'NY', 'TE', 'MT', 'RH'])
    monkeypatch.setattr(payment, 'getPaymentTypes', lambda: ['Debit', 'Visa', 'SnapliiGiftCard', 'Union Pay'])
    monkeypatch.setattr(
        payment, 'getPaymentTypeStr',
        lambda types: (types == ['ALL'], payment.getPaymentTypes() if types == ['ALL'] else types),
    )
    sessions, closed, requested = {}, [], []

    def factory(store):
        requested.append(store)

        async def dependency():
            try:
                yield sessions[store]
            finally:
                closed.append(store)
        return dependency

    monkeypatch.setattr(payment, 'get_db_store_sqlserver_factory', factory)

    def add(store, rows):
        sessions[store] = Mock(execute=AsyncMock(return_value=Mock(all=Mock(return_value=rows))))
        return sessions[store]

    return add, requested, closed


@pytest.mark.asyncio
async def test_daily_multiple_stores_normalization_and_other(store_db):
    add, requested, closed = store_db
    day = date(2026, 10, 27)
    ms = add('MS', [
        (day, 'Drwr Debit card   ', Decimal('10.10')),
        (day, 'Drwr Debit   ', Decimal('2.20')),
        (day, 'Drwr SnapliiGiftCard ', Decimal('5.00')),
        (day, 'unknown', Decimal('-1.00')),
        (day, None, Decimal('3.00')),
    ])
    add('NY', [(day, 'Drwr Visa ', Decimal('4.00'))])
    result = await payment.getPaymentDateData(DatePaymentSearchParameter(
        FromDate=day, ToDate=day, Store=['MS', 'NY'], PaymentType=['ALL'],
    ))
    amounts = {(d.store, d.paymenttype): d.amountaftertax for d in result.details}
    assert amounts == {('MS', 'Debit'): 12.3, ('MS', 'SnapliiGiftCard'): 5,
                       ('MS', 'other'): 2, ('NY', 'Visa'): 4, ('NY', 'other'): 0}
    assert result.summary.totalamountaftertax == 23.3
    assert result.summary.items == len(result.details)
    assert all(d.amountbeforetax == d.amountaftertax and d.transactions == 0 for d in result.details)
    assert requested == closed == ['MS', 'NY']
    query, params = ms.execute.call_args.args
    assert params == {'from_date': day, 'to_date': date(2026, 10, 28)}
    assert 'f.F1034 BETWEEN 1200 AND 1299' in str(query)
    assert 'f.F254 < :to_date' in str(query)


@pytest.mark.asyncio
async def test_specific_type_filter_and_duplicate_store(store_db):
    add, requested, _ = store_db
    day = date(2026, 10, 27)
    add('MS', [(day, 'Drwr Debit card', Decimal('1')), (day, 'Drwr Visa', Decimal('2')),
               (day, 'unconfigured', Decimal('3'))])
    result = await payment.getPaymentDateData(DatePaymentSearchParameter(
        FromDate=day, ToDate=day, Store=['MS', 'MS'], PaymentType=['Visa'],
    ))
    assert requested == ['MS']
    assert [(d.paymenttype, d.amountaftertax) for d in result.details] == [('Visa', 2)]


@pytest.mark.asyncio
async def test_month_all_stores_and_year_boundary(store_db):
    add, requested, closed = store_db
    for store in payment.getStore():
        add(store, [('2026-12', 'Drwr Visa', Decimal('2.50'))])
    result = await payment.getPaymentMonthData(MonthPaymentSearchParameter(
        FromMonth='2026-11', ToMonth='2026-12', Store=['ALL'], PaymentType=['Visa'],
    ))
    assert requested == closed == payment.getStore()
    assert len(result.details) == 5
    assert result.summary.totalamountbeforetax == result.summary.totalamountaftertax == 12.5
    assert all(d.month == '2026-12' and d.transactions == 0 for d in result.details)


@pytest.mark.asyncio
async def test_month_bounds_and_empty_result(store_db):
    add, _, _ = store_db
    db = add('MS', [])
    result = await payment.getPaymentMonthData(MonthPaymentSearchParameter(
        FromMonth='2024-02', ToMonth='2024-02', Store=['MS'], PaymentType=['ALL'],
    ))
    query, params = db.execute.call_args.args
    assert params == {'from_date': date(2024, 2, 1), 'to_date': date(2024, 3, 1)}
    assert 'CONVERT(char(7), f.F254, 120)' in str(query)
    assert result.details == []
    assert result.summary.items == result.summary.totalamountaftertax == 0


@pytest.mark.asyncio
async def test_database_error_closes_session(store_db):
    add, _, closed = store_db
    db = add('MS', [])
    db.execute.side_effect = RuntimeError('database unavailable')
    with pytest.raises(RuntimeError, match='database unavailable'):
        await payment.getPaymentDateData(DatePaymentSearchParameter(
            FromDate=date(2026, 10, 27), ToDate=date(2026, 10, 27),
            Store=['MS'], PaymentType=['ALL'],
        ))
    assert closed == ['MS']


def test_validation_and_specific_prefix(store_db):
    assert payment.check_store_payment(['ALL'], ['ALL'])
    assert not payment.check_store_payment(['ALL', 'MS'], ['ALL'])
    assert not payment.check_store_payment([], ['ALL'])
    assert not payment.check_store_payment(['MS'], None)
    assert not payment.check_payment_month(MonthPaymentSearchParameter(FromMonth='2026-13'))
    assert payment._payment_type('Drwr Visa Gold ', ['Visa', 'Visa Gold']) == 'Visa Gold'


@pytest.mark.asyncio
async def test_graphql_resolvers_await_payment_queries(monkeypatch):
    import mygraphql

    date_result, month_result = object(), object()
    daily = AsyncMock(return_value=date_result)
    monthly = AsyncMock(return_value=month_result)
    monkeypatch.setattr(mygraphql, 'check_payment_date', lambda param: True)
    monkeypatch.setattr(mygraphql, 'check_payment_month', lambda param: True)
    monkeypatch.setattr(mygraphql, 'getPaymentDateData', daily)
    monkeypatch.setattr(mygraphql, 'getPaymentMonthData', monthly)
    date_param = DatePaymentSearchParameter()
    month_param = MonthPaymentSearchParameter()
    assert await mygraphql.get_date_payment_data(date_param) is date_result
    assert await mygraphql.get_month_payment_data(month_param) is month_result
    daily.assert_awaited_once_with(date_param)
    monthly.assert_awaited_once_with(month_param)
