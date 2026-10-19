
import xmlrpc.client
import ssl
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from order_sync.config import get_config


# ============================================================
# 1. Configuration
# ============================================================

settings = get_config()["odoo_order_sync"]

url = settings["url"].rstrip("/")
db = settings["db"]
username = settings["username"]
password = settings["password"]

context = (
    ssl.create_default_context()
    if settings.getboolean("verify_ssl")
    else ssl._create_unverified_context()
)


# ============================================================
# 2. Login
# ============================================================

common = xmlrpc.client.ServerProxy(
    f"{url}/xmlrpc/2/common",
    context=context
)

uid = common.authenticate(db, username, password, {})

if not uid:
    raise Exception("Odoo login failed")

print("uid =", uid)


# ============================================================
# 3. Object API
# ============================================================

models = xmlrpc.client.ServerProxy(
    f"{url}/xmlrpc/2/object",
    context=context
)


def execute(model, method, args=None, kwargs=None):
    return models.execute_kw(
        db,
        uid,
        password,
        model,
        method,
        args if args is not None else [],
        kwargs if kwargs is not None else {},
    )


# ============================================================
# 4. Check Sale Order fields
# ============================================================

def check_sale_order_fields():
    fields = execute(
        "sale.order",
        "fields_get",
        [],
        {
            "attributes": [
                "string",
                "type",
                "relation",
                "selection",
            ]
        },
    )

    print("\n========== Sale Order Fields ==========")

    for field_name in [
        "state",
        "invoice_ids",
        "invoice_status",
        "warehouse_id",
        "order_line",
        "partner_id",
        "user_id",
        "company_id",
    ]:
        print(field_name, "=", fields.get(field_name))

    return fields


# ============================================================
# 5. Get Sale Orders
# ============================================================

def get_orders(limit=100):
    return execute(
        "sale.order",
        "search_read",
        [[]],
        {
            "fields": [
                "id",
                "name",
                "date_order",
                "partner_id",
                "user_id",
                "company_id",
                "state",
                "invoice_ids",
                "invoice_status",
                "warehouse_id",
                "amount_total",
                "create_date",
                "write_date",
                "order_line",
            ],
            "limit": limit,
            "order": "id desc",
        },
    )


# ============================================================
# 6. Get Invoice Details
# ============================================================

def get_invoices(invoice_ids):
    if not invoice_ids:
        return []

    return execute(
        "account.move",
        "read",
        [invoice_ids],
        {
            "fields": [
                "id",
                "name",
                "move_type",
                "state",
                "payment_state",
                "partner_id",
                "invoice_date",
                "amount_total",
                "create_date",
                "write_date",
            ]
        },
    )


# ============================================================
# 7. Get Customer / Partner Details
# ============================================================

PARTNER_FIELDS = [
    "id",
    "name",
    "display_name",
    "is_company",
    "parent_id",
    "commercial_partner_id",
    "ref",
    "active",
    "customer_rank",
]


def get_partners(partner_ids):
    if not partner_ids:
        return []

    return execute(
        "res.partner",
        "read",
        [sorted(set(partner_ids))],
        {"fields": PARTNER_FIELDS},
    )


# ============================================================
# 8. Get All Customer Companies
# ============================================================

def get_customer_companies():
    return execute(
        "res.partner",
        "search_read",
        [[
            ("is_company", "=", True),
            ("customer_rank", ">", 0),
        ]],
        {
            "fields": PARTNER_FIELDS,
            "order": "id asc",
        },
    )


# ============================================================
# 9. Check whether order is ready for SAP
# ============================================================

def is_ready_for_sap(order, invoices):
    if order["state"] != "sale":
        return False

    return any(
        inv["move_type"] == "out_invoice"
        and inv["state"] in ("draft", "posted")
        for inv in invoices
    )


# ============================================================
# 10. Test
# ============================================================

check_sale_order_fields()

# ------------------------------------------------------------
# A. List Customer Companies
# ------------------------------------------------------------

print("\n========== Odoo Customer Companies ==========")

companies = get_customer_companies()

print("Customer company count:", len(companies))

for company in companies:
    print("-----------------------------------")
    print("Company ID:", company["id"])
    print("Company Name:", company["name"])
    print("Reference:", company["ref"])
    print("Customer Rank:", company["customer_rank"])
    print("Active:", company["active"])


# ------------------------------------------------------------
# B. Get Orders
# ------------------------------------------------------------

orders = get_orders(limit=100)

print("\nOrder count =", len(orders))


# ------------------------------------------------------------
# C. Batch Fetch Invoices
# ------------------------------------------------------------

all_invoice_ids = sorted({
    invoice_id
    for order in orders
    for invoice_id in order.get("invoice_ids", [])
})

all_invoices = get_invoices(all_invoice_ids)

invoice_map = {
    inv["id"]: inv
    for inv in all_invoices
}


# ------------------------------------------------------------
# D. Batch Fetch Order Partners
# ------------------------------------------------------------

order_partner_ids = [
    order["partner_id"][0]
    for order in orders
    if order.get("partner_id")
]

partners = get_partners(order_partner_ids)

partner_map = {
    partner["id"]: partner
    for partner in partners
}


# ------------------------------------------------------------
# E. Fetch Commercial Partners
# ------------------------------------------------------------

commercial_partner_ids = [
    partner["commercial_partner_id"][0]
    for partner in partners
    if partner.get("commercial_partner_id")
]

commercial_partners = get_partners(commercial_partner_ids)

commercial_partner_map = {
    partner["id"]: partner
    for partner in commercial_partners
}


# ------------------------------------------------------------
# F. Print Orders + Customer + Invoice
# ------------------------------------------------------------

ready_count = 0

for order in orders:
    print("\n" + "=" * 65)

    print("Order ID:", order["id"])
    print("Order:", order["name"])
    print("Date:", order["date_order"])
    print("State:", order["state"])
    print("Odoo Company:", order["company_id"])
    print("Salesperson:", order["user_id"])
    print("Warehouse:", order["warehouse_id"])
    print("Total:", order["amount_total"])
    print("Lines:", order["order_line"])
    print("Write Date:", order["write_date"])

    # Customer
    print("\n--- Customer / Partner ---")

    partner_value = order.get("partner_id")
    partner_id = partner_value[0] if partner_value else None
    partner = partner_map.get(partner_id)

    if partner:
        print("Partner ID:", partner["id"])
        print("Partner Name:", partner["name"])
        print("Is Company:", partner["is_company"])
        print("Parent:", partner["parent_id"])
        print("Reference:", partner["ref"])

        commercial_value = partner.get("commercial_partner_id")

        if commercial_value:
            commercial_id = commercial_value[0]
            commercial = commercial_partner_map.get(commercial_id)

            print("Commercial Partner ID:", commercial_id)
            print("Commercial Partner Name:",
                  commercial["name"] if commercial else commercial_value[1])

            if commercial:
                print("Commercial Partner Ref:", commercial["ref"])
        else:
            print("Commercial Partner: Not found")
    else:
        print("Partner: Not found")

    # Invoice
    print("\n--- Invoices ---")

    invoice_ids = order.get("invoice_ids", [])

    invoices = [
        invoice_map[inv_id]
        for inv_id in invoice_ids
        if inv_id in invoice_map
    ]

    print("Invoice IDs:", invoice_ids)
    print("Invoice Status:", order["invoice_status"])

    if not invoices:
        print("No invoices found.")
    else:
        for invoice in invoices:
            print("  Invoice ID:", invoice["id"])
            print("  Number:", invoice["name"])
            print("  Type:", invoice["move_type"])
            print("  State:", invoice["state"])
            print("  Payment State:", invoice["payment_state"])
            print("  Invoice Date:", invoice["invoice_date"])
            print("  Amount:", invoice["amount_total"])
            print("  Write Date:", invoice["write_date"])
            print("  -------------------------")

    ready = is_ready_for_sap(order, invoices)

    print("\nReady for SAP:", ready)

    if ready:
        ready_count += 1


# ------------------------------------------------------------
# G. Summary
# ------------------------------------------------------------

print("\n" + "=" * 65)
print("SUMMARY")
print("=" * 65)

print("Total Orders:", len(orders))
print("Ready for SAP:", ready_count)
print("Not Ready:", len(orders) - ready_count)
print("Customer Companies:", len(companies))
