from datetime import datetime, time, timedelta, timezone
import ssl
import xmlrpc.client
from zoneinfo import ZoneInfo

from .config import get_config


class TimeoutTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout, context):
        super().__init__(context=context)
        self.timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


def today_domain(now=None):
    settings = get_config()["celery_order_sync"]
    tz = ZoneInfo(settings["timezone"])
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    field = settings["odoo_date_field"]
    if field not in {"create_date", "write_date", "date_order"}:
        raise ValueError("odoo_date_field must be create_date, write_date or date_order")
    fmt = "%Y-%m-%d %H:%M:%S"
    return [
        ["state", "=", "sale"],
        [field, ">=", start.astimezone(timezone.utc).strftime(fmt)],
        [field, "<", end.astimezone(timezone.utc).strftime(fmt)],
    ]


class OdooClient:
    def __init__(self):
        self.settings = get_config()["odoo_order_sync"]
        context = ssl.create_default_context()
        if not self.settings.getboolean("verify_ssl"):
            context = ssl._create_unverified_context()

        def proxy(endpoint):
            return xmlrpc.client.ServerProxy(
                f"{self.settings['url'].rstrip('/')}/xmlrpc/2/{endpoint}",
                transport=TimeoutTransport(self.settings.getfloat("timeout_seconds"), context),
            )

        common = proxy("common")
        with common:
            self.uid = common.authenticate(
                self.settings["db"], self.settings["username"], self.settings["password"], {}
            )
        if not self.uid:
            raise ValueError("Odoo login failed; check [odoo_order_sync]")
        self.models = proxy("object")

    def close(self):
        self.models.__exit__(None, None, None)

    def execute(self, model, method, args, **kwargs):
        return self.models.execute_kw(
            self.settings["db"], self.uid, self.settings["password"],
            model, method, args, kwargs,
        )

    def iter_today_orders(self):
        domain = today_domain()
        page_size = get_config()["celery_order_sync"].getint("odoo_page_size")
        if page_size <= 0:
            raise ValueError("odoo_page_size must be positive")
        last_id = 0
        while True:
            orders = self.execute(
                "sale.order", "search_read", [domain + [["id", ">", last_id]]],
                fields=["id", "name"], limit=page_size, order="id asc",
            )
            if not orders:
                return
            yield from orders
            last_id = orders[-1]["id"]

    def read_one(self, model, record_id, fields):
        records = self.execute(model, "read", [[record_id]], fields=fields)
        if len(records) != 1:
            raise ValueError(f"Missing Odoo {model} record {record_id}")
        return records[0]

    def build_sap_payload(self, sync_order):
        settings = get_config()["sap_order_sync"]
        partner_field = settings["odoo_partner_cardcode_field"].strip()
        product_field = settings["odoo_product_itemcode_field"].strip()
        external_field = settings["external_key_field"].strip()
        if not partner_field or not product_field or not external_field:
            raise ValueError("Configure SAP customer/product mapping and external_key_field first")
        order = self.read_one(
            "sale.order", sync_order["odoo_order_id"],
            ["name", "state", "partner_id", "order_line", "date_order", "warehouse_id"],
        )
        if order["state"] != "sale":
            raise ValueError("Odoo order is no longer confirmed")
        partner = self.read_one("res.partner", order["partner_id"][0], [partner_field])
        card_code = partner.get(partner_field)
        if not isinstance(card_code, str) or not card_code.strip():
            raise ValueError("Odoo partner has no SAP CardCode mapping")
        lines = self.execute(
            "sale.order.line", "read", [order["order_line"]],
            fields=["display_type", "product_id", "product_uom_qty", "price_unit", "discount"],
        )
        product_ids = sorted({line["product_id"][0] for line in lines
                              if not line["display_type"] and line["product_id"]})
        products = self.execute("product.product", "read", [product_ids], fields=[product_field])
        codes = {product["id"]: product.get(product_field) for product in products}
        warehouse_code = settings.get("warehouse_code", "").strip()
        warehouse_field = settings.get("odoo_warehouse_code_field", "").strip()
        if warehouse_field:
            if not order["warehouse_id"]:
                raise ValueError("Odoo order has no warehouse")
            warehouse = self.read_one("stock.warehouse", order["warehouse_id"][0], [warehouse_field])
            warehouse_code = warehouse.get(warehouse_field)
            if not isinstance(warehouse_code, str) or not warehouse_code.strip():
                raise ValueError("Odoo warehouse has no SAP WarehouseCode mapping")
        document_lines = []
        for line in lines:
            if line["display_type"]:
                continue
            item_code = codes.get(line["product_id"][0]) if line["product_id"] else None
            if not isinstance(item_code, str) or not item_code.strip():
                raise ValueError(f"Odoo line {line['id']} has no SAP ItemCode mapping")
            if line["product_uom_qty"] <= 0:
                raise ValueError(f"Odoo line {line['id']} quantity must be positive")
            sap_line = {"ItemCode": item_code.strip(), "Quantity": line["product_uom_qty"],
                        "UnitPrice": line["price_unit"], "DiscountPercent": line["discount"]}
            if warehouse_code:
                sap_line["WarehouseCode"] = warehouse_code
            document_lines.append(sap_line)
        if not document_lines:
            raise ValueError("Odoo order has no product lines")
        doc_date = datetime.strptime(order["date_order"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        ).astimezone(ZoneInfo(get_config()["celery_order_sync"]["timezone"])).date().isoformat()
        return {"CardCode": card_code.strip(), "NumAtCard": order["name"],
                "DocDate": doc_date, external_field: sync_order["sap_external_key"],
                "DocumentLines": document_lines}
