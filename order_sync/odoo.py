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
    fmt = "%Y-%m-%d %H:%M:%S"
    return [
        ["move_type", "=", "out_invoice"],
        ["state", "in", ["draft", "posted"]],
        ["write_date", ">=", start.astimezone(timezone.utc).strftime(fmt)],
        ["write_date", "<", end.astimezone(timezone.utc).strftime(fmt)],
    ]


def sap_document_date(date_order, settings, now=None):
    source = settings.get("document_date_source", "order_date").strip().lower()
    tz = ZoneInfo(get_config()["celery_order_sync"]["timezone"])
    if source == "today":
        date_value = now or datetime.now(timezone.utc)
    elif source == "order_date":
        date_value = datetime.strptime(date_order, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    else:
        try:
            fixed_date = datetime.strptime(source, "%Y-%m-%d").date().isoformat()
            if fixed_date != source:
                raise ValueError("Expected YYYY-MM-DD")
        except ValueError:
            raise ValueError(
                "SAP document_date_source must be today, order_date, "
                "or a valid date in YYYY-MM-DD format (e.g. 2023-10-02)"
            ) from None
        return fixed_date
    return date_value.astimezone(tz).date().isoformat()


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
        """Find confirmed sale orders linked to customer invoices updated today."""
        domain = today_domain()
        page_size = get_config()["celery_order_sync"].getint("odoo_page_size")
        if page_size <= 0:
            raise ValueError("odoo_page_size must be positive")
        last_id = 0
        seen_order_ids = set()
        while True:
            invoices = self.execute(
                "account.move", "search_read", [domain + [["id", ">", last_id]]],
                fields=["id", "invoice_line_ids"], limit=page_size, order="id asc",
            )
            if not invoices:
                return
            last_id = invoices[-1]["id"]
            invoice_line_ids = sorted({line_id for invoice in invoices
                                       for line_id in invoice["invoice_line_ids"]})
            if not invoice_line_ids:
                continue
            invoice_lines = self.execute(
                "account.move.line", "read", [invoice_line_ids], fields=["sale_line_ids"],
            )
            sale_line_ids = sorted({line_id for line in invoice_lines
                                    for line_id in line["sale_line_ids"]})
            if not sale_line_ids:
                continue
            sale_lines = self.execute(
                "sale.order.line", "read", [sale_line_ids], fields=["order_id"],
            )
            order_ids = sorted({line["order_id"][0] for line in sale_lines
                                if line["order_id"]} - seen_order_ids)
            if not order_ids:
                continue
            orders = self.execute(
                "sale.order", "search_read",
                [[["id", "in", order_ids], ["state", "=", "sale"]]],
                fields=["id", "name"], order="id asc",
            )
            for order in orders:
                seen_order_ids.add(order["id"])
                yield order

    def read_one(self, model, record_id, fields):
        records = self.execute(model, "read", [[record_id]], fields=fields)
        if len(records) != 1:
            raise ValueError(f"Missing Odoo {model} record {record_id}")
        return records[0]

    def build_sap_payload(self, sync_order):
        print(f"DEBUG: Building SAP payload for Odoo order {sync_order['odoo_order_id']}")
        settings = get_config()["sap_order_sync"]
        product_field = settings["odoo_product_itemcode_field"].strip()
        external_field = settings["external_key_field"].strip()
        if not product_field or not external_field:
            raise ValueError("Configure SAP product mapping and external_key_field first")
        order = self.read_one(
            "sale.order", sync_order["odoo_order_id"],
            ["name", "state", "partner_id", "order_line", "date_order", "warehouse_id"],
        )
        if order["state"] != "sale":
            raise ValueError("Odoo order is no longer confirmed")
        if not order["partner_id"]:
            raise ValueError("Odoo order has no customer")
        partner = self.read_one(
            "res.partner", order["partner_id"][0], ["commercial_partner_id"],
        )
        commercial_partner = partner.get("commercial_partner_id")
        if not commercial_partner:
            raise ValueError(f"Odoo partner {order['partner_id'][0]} has no commercial_partner_id")
        commercial_partner_id = commercial_partner[0]
        config = get_config()
        mapping = config["sap_customer_mapping"] if "sap_customer_mapping" in config else {}
        card_code = mapping.get(str(commercial_partner_id))
        if not isinstance(card_code, str) or not card_code.strip():
            raise ValueError(
                f"No SAP CardCode mapping for Odoo commercial partner {commercial_partner_id}; "
                "configure [sap_customer_mapping]"
            )
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
            product_id = line["product_id"][0] if line["product_id"] else None
            item_code = codes.get(product_id)
            if item_code == "Delivery_007":
                continue

            if not isinstance(item_code, str) or not item_code.strip():
                raise ValueError(
                    f"Odoo line {line['id']}, "
                    f"product_id={product_id}, "
                    f"product_name={line.get('product_id')}, "
                    f"field={product_field}, "
                    f"value={item_code!r}: "
                    "missing SAP ItemCode mapping"
                )
            if line["product_uom_qty"] <= 0:
                raise ValueError(f"Odoo line {line['id']} quantity must be positive")
            sap_line = {"ItemCode": item_code.strip(), "Quantity": line["product_uom_qty"],
                        "UnitPrice": line["price_unit"], "DiscountPercent": line["discount"]}
            if warehouse_code:
                sap_line["WarehouseCode"] = warehouse_code
            document_lines.append(sap_line)
        if not document_lines:
            raise ValueError("Odoo order has no product lines")
        doc_date = sap_document_date(order["date_order"], settings)
        print(f"DEBUG: SAP payload for Odoo order {order['id']} (name={order['name']}): "
              f"CardCode={card_code.strip()}, NumAtCard={order['name']}, "
              f"DocDate={doc_date}, DocDueDate={doc_date}, "
              f"{external_field}={sync_order['sap_external_key']}, "
              f"DocumentLines={document_lines}")
        
        return {"CardCode": card_code.strip(), "NumAtCard": order["name"],
                "DocDate": doc_date, "DocDueDate": doc_date,
                external_field: sync_order["sap_external_key"],
                "DocumentLines": document_lines}
