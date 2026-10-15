import xmlrpc.client
import ssl

from pathlib import Path
import sys

# Allow both `python Testing/test_*.py` and module execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from order_sync.config import get_config

settings = get_config()['odoo_order_sync']
url = settings['url'].rstrip('/')
db = settings['db']
username = settings['username']
password = settings['password']
context = ssl.create_default_context() if settings.getboolean('verify_ssl') else ssl._create_unverified_context()

# ============================================================
# 1. Login
# ============================================================

common = xmlrpc.client.ServerProxy(
    f"{url}/xmlrpc/2/common",
    context=context
)

uid = common.authenticate(
    db,
    username,
    password,
    {}
)

if not uid:
    raise Exception("Odoo login failed")

print("uid =", uid)


# ============================================================
# 2. Object API
# ============================================================

models = xmlrpc.client.ServerProxy(
    f"{url}/xmlrpc/2/object",
    context=context
)


# ============================================================
# 3. Get orders
# ============================================================

def get_orders(limit=100):

    orders = models.execute_kw(
        db,
        uid,
        password,
        "sale.order",
        "search_read",

        # domain
        [[]],

        {
            "fields": [
                "id",
                "name",
                "date_order",
                "partner_id",
                "state",
                "warehouse_id",
                "amount_total",
                "create_date",
                "write_date",
                "order_line",
                "write_date",
            ],

            "limit": limit,
            "order": "id desc",
        }
    )

    return orders


# ============================================================
# 4. Test
# ============================================================

orders = get_orders()

print("order count =", len(orders))

for order in orders:
    print("-----------------------------------")
    print("ID:", order["id"])
    print("Order:", order["name"])
    print("Date:", order["date_order"])
    print("Customer:", order["partner_id"])
    print("State:", order["state"])
    print("Warehouse:", order["warehouse_id"])
    print("Total:", order["amount_total"])
    print("Lines:", order["order_line"])
    print("write_date:", order["write_date"])

def get_sale_order_states():
    fields = models.execute_kw(
        db,
        uid,
        password,
        "sale.order",
        "fields_get",
        [],
        {
            "attributes": [
                "string",
                "type",
                "selection",
            ]
        }
    )

    return fields["state"]


state_info = get_sale_order_states()

print(state_info)