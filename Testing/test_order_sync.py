from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests

from celery_app import celery_app
from order_sync import tasks
from order_sync.odoo import OdooClient, today_domain
from order_sync.sap import SapClient


def order(attempt=1):
    return {"id": 10, "odoo_db": "BT", "odoo_order_id": 107,
            "sap_external_key": "ODOO-BT-107", "attempt_count": attempt, "max_attempts": 5}


def test_exactly_two_registered_periodic_tasks():
    celery_app.loader.import_default_modules()
    schedule = celery_app.conf.beat_schedule
    assert len(schedule) == 2
    assert all(entry["task"] in celery_app.tasks for entry in schedule.values())
    assert celery_app.conf.broker_transport_options["confirm_publish"] is True


def test_today_is_local_day_and_handles_dst():
    domain = today_domain(datetime(2026, 11, 1, 16, tzinfo=timezone.utc))
    assert domain == [["move_type", "=", "out_invoice"],
                      ["state", "in", ["draft", "posted"]],
                      ["write_date", ">=", "2026-11-01 04:00:00"],
                      ["write_date", "<", "2026-11-02 05:00:00"]]


def test_invoice_poll_resolves_orders_and_deduplicates_across_pages(monkeypatch):
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: {
        "celery_order_sync": type("Settings", (dict,), {"getint": lambda s, k: 2})(
            timezone="America/Toronto")})
    client = OdooClient.__new__(OdooClient)
    client.execute = Mock(side_effect=[
        [{"id": 10, "invoice_line_ids": [100, 101]},
         {"id": 11, "invoice_line_ids": [102]}],
        [{"sale_line_ids": [200, 201]}, {"sale_line_ids": []}, {"sale_line_ids": [200]}],
        [{"order_id": [1, "SO1"]}, {"order_id": [2, "SO2"]}],
        [{"id": 1, "name": "SO1"}, {"id": 2, "name": "SO2"}],
        [{"id": 12, "invoice_line_ids": [103]}],
        [{"sale_line_ids": [200, 202]}],
        [{"order_id": [1, "SO1"]}, {"order_id": [3, "SO3"]}],
        [{"id": 3, "name": "SO3"}],
        [],
    ])
    assert list(client.iter_today_orders()) == [
        {"id": 1, "name": "SO1"}, {"id": 2, "name": "SO2"}, {"id": 3, "name": "SO3"}]
    calls = client.execute.call_args_list
    assert calls[0].args[:2] == ("account.move", "search_read")
    assert calls[0].kwargs["limit"] == 2
    assert calls[1].args == ("account.move.line", "read", [[100, 101, 102]])
    assert calls[2].args == ("sale.order.line", "read", [[200, 201]])
    assert calls[3].args == ("sale.order", "search_read",
                            [[["id", "in", [1, 2]], ["state", "=", "sale"]]])
    assert calls[4].args[2][0][-1] == ["id", ">", 11]
    assert calls[7].args[2] == [[["id", "in", [3]], ["state", "=", "sale"]]]
    assert calls[8].args[2][0][-1] == ["id", ">", 12]


@pytest.mark.parametrize("responses", [
    [[{"id": 1, "invoice_line_ids": []}], []],
    [[{"id": 1, "invoice_line_ids": [10]}], [{"sale_line_ids": []}], []],
    [[{"id": 1, "invoice_line_ids": [10]}], [{"sale_line_ids": [20]}],
     [{"order_id": False}], []],
    [[{"id": 1, "invoice_line_ids": [10]}], [{"sale_line_ids": [20]}],
     [{"order_id": [30, "Unconfirmed"]}], [], []],
])
def test_invoice_poll_skips_unlinked_or_unconfirmed_orders(responses):
    client = OdooClient.__new__(OdooClient)
    client.execute = Mock(side_effect=responses)
    assert list(client.iter_today_orders()) == []


@pytest.mark.parametrize("post_started,attempt,expected", [(False, 1, "retry"),
                         (False, 5, "review"), (True, 1, "review")])
def test_timeout_retry_only_before_create(post_started, attempt, expected):
    assert tasks.failure_status(order(attempt), requests.Timeout(), post_started) == expected


def test_validation_error_is_review():
    assert tasks.failure_status(order(), ValueError("missing mapping"), False) == "review"


def setup_worker(monkeypatch, sap):
    monkeypatch.setattr(tasks.db, "claim_order", Mock(return_value=order()))
    finish = Mock()
    monkeypatch.setattr(tasks.db, "finish_order", finish)
    monkeypatch.setattr(tasks, "SapClient", Mock(return_value=sap))
    return finish


def test_existing_sap_order_does_not_post(monkeypatch):
    existing = {"DocEntry": 42, "DocNum": 10042}
    sap = Mock()
    sap.find_order.return_value = existing
    finish = setup_worker(monkeypatch, sap)
    odoo = Mock()
    monkeypatch.setattr(tasks, "OdooClient", odoo)
    assert tasks.sync_order_to_sap.run(10)["status"] == "done"
    sap.create_order.assert_not_called()
    odoo.assert_not_called()
    finish.assert_called_once_with(order(), "done", sap_order=existing)


def test_duplicate_message_does_not_contact_sap(monkeypatch):
    monkeypatch.setattr(tasks.db, "claim_order", Mock(return_value=None))
    sap = Mock()
    monkeypatch.setattr(tasks, "SapClient", sap)
    assert tasks.sync_order_to_sap.run(10)["status"] == "skipped"
    sap.assert_not_called()


def test_post_timeout_moves_to_review(monkeypatch):
    sap = Mock()
    sap.find_order.return_value = None
    sap.create_order.side_effect = requests.Timeout("lost response")
    finish = setup_worker(monkeypatch, sap)
    monkeypatch.setattr(tasks, "OdooClient", Mock(return_value=Mock()))
    assert tasks.sync_order_to_sap.run(10)["status"] == "review"
    assert finish.call_args.args[1] == "review"


def test_db_failure_after_successful_post_is_not_retried(monkeypatch):
    sap = Mock()
    sap.find_order.return_value = None
    sap.create_order.return_value = {"DocEntry": 42, "DocNum": 10042}
    finish = setup_worker(monkeypatch, sap)
    finish.side_effect = RuntimeError("database offline")
    monkeypatch.setattr(tasks, "OdooClient", Mock(return_value=Mock()))
    with pytest.raises(RuntimeError, match="database offline"):
        tasks.sync_order_to_sap.run(10)
    assert finish.call_count == 1
    assert finish.call_args.args[1] == "done"
    sap.create_order.assert_called_once()


def test_publish_db_failure_does_not_reset_already_sent_event(monkeypatch):
    monkeypatch.setattr(tasks.db, "enqueue_due_retries", Mock())
    event = {"id": 1, "order_sync_id": 10}
    monkeypatch.setattr(tasks.db, "claim_outbox", Mock(return_value=event))
    monkeypatch.setattr(tasks.sync_order_to_sap, "apply_async", Mock())
    finish = Mock(side_effect=RuntimeError("database offline"))
    monkeypatch.setattr(tasks.db, "finish_publish", finish)
    with pytest.raises(RuntimeError):
        tasks.publish_outbox.run()
    finish.assert_called_once_with(event)


@pytest.mark.parametrize("partner_id,company_id,card_code", [
    (52, 7, "C100001"), (8, 8, "C100002"),
    (90, 9, "C100035"), (88, 9, "C100035"), (10, 10, "C100003"),
])
def test_mapping_builds_lines_and_skips_sections(monkeypatch, partner_id, company_id, card_code):
    settings = {"odoo_product_itemcode_field": "default_code",
                "external_key_field": "NumAtCard", "warehouse_code": "01"}
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: {
        "sap_order_sync": settings, "celery_order_sync": {"timezone": "America/Toronto"},
        "sap_customer_mapping": {"7": "C100001", "8": "C100002",
                                 "9": "C100035", "10": "C100003"}})
    client = OdooClient.__new__(OdooClient)
    client.read_one = Mock(side_effect=[
        {"name": "S00107", "state": "sale", "partner_id": [partner_id, "Customer"],
         "order_line": [5, 6], "date_order": "2026-10-14 12:00:00", "warehouse_id": [1, "WH"]},
        {"commercial_partner_id": [company_id, "Company"]},
    ])
    client.execute = Mock(side_effect=[
        [{"id": 5, "display_type": "line_section", "product_id": False},
         {"id": 6, "display_type": False, "product_id": [7, "Item"],
          "product_uom_qty": 2, "price_unit": 3.5, "discount": 10}],
        [{"id": 7, "default_code": "ITEM7"}],
    ])
    payload = client.build_sap_payload(order())
    assert payload["CardCode"] == card_code
    assert client.read_one.call_args.args == (
        "res.partner", partner_id, ["commercial_partner_id"])
    assert payload["NumAtCard"] == "ODOO-BT-107"
    assert payload["DocumentLines"] == [{"ItemCode": "ITEM7", "Quantity": 2,
        "UnitPrice": 3.5, "DiscountPercent": 10, "WarehouseCode": "01"}]


@pytest.mark.parametrize("mapping,commercial_partner", [
    ({"9": "C100035"}, [99, "Unknown company"]),
    ({"9": "  "}, [9, "Montreal"]),
    (None, [9, "Montreal"]),
    ({"9": "C100035"}, False),
])
def test_missing_customer_mapping_stops_payload_before_lines(monkeypatch, mapping, commercial_partner):
    config = {"sap_order_sync": {"odoo_product_itemcode_field": "default_code",
                                  "external_key_field": "NumAtCard"}}
    if mapping is not None:
        config["sap_customer_mapping"] = mapping
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: config)
    client = OdooClient.__new__(OdooClient)
    client.read_one = Mock(side_effect=[
        {"state": "sale", "partner_id": [90, "Customer"]},
        {"commercial_partner_id": commercial_partner},
    ])
    client.execute = Mock()
    with pytest.raises(ValueError, match="commercial_partner_id|No SAP CardCode mapping"):
        client.build_sap_payload(order())
    client.execute.assert_not_called()


@pytest.mark.parametrize("field", ["NumAtCard", "U_OdooOrderKey"])
def test_sap_filter_escapes_external_key_and_detects_duplicates(field):
    client = SapClient.__new__(SapClient)
    client.settings = {"external_key_field": field}
    client.base_url = "https://example.invalid/b1s/v1"
    client.timeout = 30
    client.session = Mock()
    response = client.session.get.return_value
    response.json.return_value = {"value": [{"DocEntry": 1}, {"DocEntry": 2}]}
    with pytest.raises(ValueError, match="Multiple SAP orders"):
        client.find_order("ODOO-O'HARE-107")
    assert client.session.get.call_args.kwargs["params"]["$filter"] == f"{field} eq 'ODOO-O''HARE-107'"
