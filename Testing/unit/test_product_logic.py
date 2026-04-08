from datetime import date, timedelta
import pytest

from routers.product import calculate_periods

def test_period_calculation_mt_weekly():
    # 假设今天是 2024-05-24 (周五，weekday 4)。MT 周从周四(3)开始。
    today = date(2024, 5, 24)
    periods = calculate_periods("MT", "W", 2, today)
    assert periods[0] == (date(2024, 5, 22), date(2024, 5, 24)) # 本周：周四到周五(今天)
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