from datetime import datetime, timezone

import pytest

from order_sync.odoo import sap_document_date


@pytest.mark.parametrize("settings,expected", [
    ({"document_date_source": "today"}, "2026-10-19"),
    ({"document_date_source": "order_date"}, "2026-10-13"),
    ({"document_date_source": "2023-10-02"}, "2023-10-02"),
    ({"document_date_source": "2024-02-29"}, "2024-02-29"),
    ({}, "2026-10-13"),
])
def test_sap_dates_use_selected_source_and_local_timezone(monkeypatch, settings, expected):
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: {
        "celery_order_sync": {"timezone": "America/Toronto"},
    })
    assert sap_document_date(
        "2026-10-14 02:00:00", settings,
        now=datetime(2026, 10, 20, 2, tzinfo=timezone.utc),
    ) == expected


@pytest.mark.parametrize("source", [
    "invalid", "2023-02-29", "2023-13-02", "2023-10-32", "2023-1-2", "20231002", "",
])
def test_invalid_date_source_is_rejected(monkeypatch, source):
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: {
        "celery_order_sync": {"timezone": "America/Toronto"},
    })
    with pytest.raises(ValueError, match="document_date_source"):
        sap_document_date("2026-10-14 12:00:00", {"document_date_source": source})
