from datetime import date, timedelta, datetime
import pytest
from unittest.mock import AsyncMock

from routers.product import calculate_periods, _get_product_common

def test_period_calculation_mt_weekly():
    # 假设今天是 2024-05-24 (周五，weekday 4)。MT 周从周四(3)开始。
    today = date(2024, 5, 24)
    periods = calculate_periods("MT", "W", 2, today)
    assert periods[0] == (date(2024, 5, 23), date(2024, 5, 24)) # 本周：周四到周五(今天)
    assert periods[1] == (date(2024, 5, 16), date(2024, 5, 22)) # 上周：周四到周三

def test_period_calculation_other_weekly():
    # 假设今天是 2024-05-24 (周五，weekday 4)。普通店从周五(4)开始。
    today = date(2024, 5, 24)
    periods = calculate_periods("B1", "W", 2, today)
    assert periods[0] == (date(2024, 5, 24), date(2024, 5, 24)) # 本周：周五到周五(今天)
    assert periods[1] == (date(2024, 5, 17), date(2024, 5, 23)) # 上周：周五到周四

def test_period_calculation_monthly():
    # 假设今天是 2024-05-24
    today = date(2024, 5, 24)
    periods = calculate_periods("B1", "M", 2, today)
    assert periods[0] == (date(2024, 5, 1), date(2024, 5, 24)) # 5月1日到今天
    assert periods[1] == (date(2024, 4, 1), date(2024, 4, 30)) # 整个4月

class FakeResult:
    def __init__(self, data):
        self._data = data

    def first(self):
        return self._data[0] if self._data else None

    def scalars(self):
        return self  # 为了支持 .scalars().all()

    def all(self):
        return self._data
    
class FakeProduct:
    def __init__(self):
        self.F01 = "123"
        self.F29 = "Apple"
        self.F255 = "苹果"
        self.F155 = "BrandX"
        self.F22 = "1kg"
        self.F17 = "FRUIT"
        self.F82 = "1"
        self.F122 = None

class FakePrice:
    def __init__(self):
        self.F01 = "123"
        self.F113 = "INSTORE"
        self.F30 = 9.99
        self.F35 = datetime(2020, 1, 1)
        self.F129 = datetime(2099, 1, 1)
        self.F33 = None
        self.F142 = 1
        self.F140 = 9.99

class FakePos:
    def __init__(self):
        self.F01 = "123"
        self.F2095 = "Pomme"
        self.F81 = 1
        self.F96 = 0
        self.F97 = 0
        self.F98 = 0
        self.F89 = 0  


@pytest.mark.asyncio
async def test_product_found():
    mock_db = AsyncMock()
    fake_product = FakeProduct()
    fake_price = FakePrice()
    fake_pos = FakePos()

    mock_db.execute.side_effect = [
        FakeResult([(fake_product, "水果")]),  # ObjTab 查询
        FakeResult([fake_price]),             # Price 查询
        FakeResult([fake_pos])                # Pos 查询
    ]

    result = await _get_product_common("123", "MT", mock_db)

    assert result["name_fr"] == fake_pos.F2095