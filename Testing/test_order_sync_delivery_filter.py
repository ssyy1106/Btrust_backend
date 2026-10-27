from unittest.mock import Mock

import pytest

from order_sync.odoo import OdooClient


@pytest.mark.parametrize("product_field", ["default_code", "barcode"])
@pytest.mark.parametrize("delivery_only", [False, True])
def test_delivery_product_is_excluded(monkeypatch, product_field, delivery_only):
    monkeypatch.setattr("order_sync.odoo.get_config", lambda: {
        "sap_order_sync": {"odoo_product_itemcode_field": product_field,
                           "external_key_field": "NumAtCard"},
        "sap_customer_mapping": {"9": "C100035"},
        "celery_order_sync": {"timezone": "America/Toronto"},
    })
    client = OdooClient.__new__(OdooClient)
    client.read_one = Mock(side_effect=[
        {"id": 107, "name": "S00107", "state": "sale",
         "partner_id": [90, "Customer"], "order_line": [5, 6, 7],
         "date_order": "2026-10-14 12:00:00", "warehouse_id": False},
        {"commercial_partner_id": [9, "Company"]},
    ])
    # Filter using the configured field before validating the line quantity.
    lines = [
        {"id": 5, "display_type": False, "product_id": [8, "Delivery"]},
        {"id": 6, "display_type": False, "product_id": [8, "Delivery"]},
    ]
    products = [{"id": 8, "default_code": "OTHER", product_field: "Delivery_007"}]
    if not delivery_only:
        lines.append({"id": 7, "display_type": False, "product_id": [7, "Item"],
                      "product_uom_qty": 2, "price_unit": 3.5, "discount": 10})
        products.append({"id": 7,
                         "default_code": "ITEM7" if product_field == "default_code" else "Delivery_007",
                         "barcode": "123456"})
    client.execute = Mock(side_effect=[lines, products])
    sync_order = {"odoo_order_id": 107, "sap_external_key": "ODOO-BT-107"}

    if delivery_only:
        with pytest.raises(ValueError, match="Odoo order has no product lines"):
            client.build_sap_payload(sync_order)
    else:
        payload = client.build_sap_payload(sync_order)
        assert payload["DocDate"] == payload["DocDueDate"] == "2026-10-14"
        assert payload["DocumentLines"] == [{
            "ItemCode": "ITEM7" if product_field == "default_code" else "123456",
            "Quantity": 2, "UnitPrice": 3.5, "DiscountPercent": 10,
        }]
    assert client.execute.call_args.kwargs["fields"] == [product_field]
