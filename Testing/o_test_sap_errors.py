from unittest.mock import Mock

import pytest
import requests

from order_sync.sap import SapClient
from order_sync import tasks


def sap_client():
    client = SapClient.__new__(SapClient)
    client.base_url = "https://example.invalid/b1s/v1"
    client.timeout = 30
    client.settings = {"external_key_field": "NumAtCard"}
    client.session = Mock()
    return client


@pytest.mark.parametrize("status", [201, 204])
def test_create_sends_prefer_header_and_resolves_order(status):
    client = sap_client()
    result = {"DocEntry": 42, "DocNum": 10042}
    response = Mock(status_code=status)
    response.json.return_value = result
    client.session.post.return_value = response
    client.find_order = Mock(return_value=result)
    payload = {"NumAtCard": "ODOO-BT-107"}
    assert client.create_order(payload) == result
    client.session.post.assert_called_once_with(
        client.base_url + "/Orders", timeout=30, json=payload,
        headers={"Prefer": "return-no-content"},
    )
    if status == 204:
        response.json.assert_not_called()
        client.find_order.assert_called_once_with("ODOO-BT-107")
    else:
        client.find_order.assert_not_called()


def test_create_204_without_sales_order_requires_review():
    client = sap_client()
    client.session.post.return_value = Mock(status_code=204)
    client.find_order = Mock(return_value=None)
    with pytest.raises(ValueError, match="Approval procedures may have created a draft") as caught:
        client.create_order({"NumAtCard": "ODOO-BT-107"})
    client.session.post.return_value.json.assert_not_called()
    assert tasks.failure_status({}, caught.value, True) == "review"


@pytest.mark.parametrize("operation,method", [("find_order", "GET"), ("create_order", "POST")])
@pytest.mark.parametrize("body", [
    b'{"error":{"code":-2028,"message":{"value":"No matching records found"}}}',
    b'<html>Endpoint not found</html>', b'',
])
def test_http_error_includes_operation_and_response(operation, method, body):
    client = sap_client()
    response = requests.Response()
    response.status_code = 404
    response.reason = "Not Found"
    response.url = client.base_url + "/Orders"
    response._content = body
    getattr(client.session, method.lower()).return_value = response
    with pytest.raises(requests.HTTPError) as caught:
        getattr(client, operation)("ODOO-BT-107" if method == "GET" else {"CardCode": "C100001"})
    message = str(caught.value)
    assert f"SAP {operation} failed" in message
    assert f"method={method}" in message
    assert "status=404 Not Found" in message
    assert "url=" + response.url in message
    assert (body.decode() if body else "<empty>") in message
    assert caught.value.response is response
    assert tasks.failure_status({"attempt_count": 1, "max_attempts": 5}, caught.value, False) == "review"
    if method == "GET":
        assert "NumAtCard eq" in message


def test_timeout_retains_type_and_does_not_log_login_credentials():
    client = sap_client()
    client.settings.update(company_db="TEST", username="manager", password="secret-password")
    client.session.post.side_effect = requests.Timeout("connection timed out")
    with pytest.raises(requests.Timeout) as caught:
        client.login()
    assert "SAP login failed" in str(caught.value)
    assert "connection timed out" in str(caught.value)
    assert "secret-password" not in str(caught.value)
    assert tasks.failure_status({"attempt_count": 1, "max_attempts": 5}, caught.value, False) == "retry"


@pytest.mark.parametrize("stage", ["find_order", "create_order"])
def test_worker_persists_failure_stage(monkeypatch, stage):
    order = {"odoo_db": "BT", "sap_external_key": "ODOO-BT-107"}
    sap = Mock()
    sap.find_order.return_value = None
    getattr(sap, stage).side_effect = requests.HTTPError("SAP error details")
    finish = Mock()
    monkeypatch.setattr(tasks.db, "claim_order", Mock(return_value=order))
    monkeypatch.setattr(tasks.db, "finish_order", finish)
    monkeypatch.setattr(tasks, "get_config", lambda: {"odoo_order_sync": {"db": "BT"}})
    monkeypatch.setattr(tasks, "SapClient", lambda: sap)
    monkeypatch.setattr(tasks, "OdooClient", Mock(return_value=Mock()))
    assert tasks.sync_order_to_sap.run(1)["status"] == "review"
    assert finish.call_args.kwargs["error"] == f"stage=sap.{stage}; HTTPError: SAP error details"
    if stage == "find_order":
        sap.create_order.assert_not_called()
