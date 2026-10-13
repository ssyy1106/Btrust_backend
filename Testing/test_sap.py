import requests
import urllib3
import json

# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://hanabtrust:50000/b1s/v1"

#COMPANY_DB = "SBO_BTRUST_LIVE"
COMPANY_DB = "UPDATEROW_TEST_BTRUST"
USERNAME = "manager"
PASSWORD = "258258"

# 测试环境如果使用 self-signed certificate
VERIFY_SSL = False

if not VERIFY_SSL:
    urllib3.disable_warnings(
        urllib3.exceptions.InsecureRequestWarning
    )


# ============================================================
# Create HTTP Session
# ============================================================

session = requests.Session()
session.verify = VERIFY_SSL


# ============================================================
# Login
# ============================================================

def login():
    url = f"{BASE_URL}/Login"

    payload = {
        "CompanyDB": COMPANY_DB,
        "UserName": USERNAME,
        "Password": PASSWORD
    }

    response = session.post(
        url,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("=== Login Success ===")
    print("SessionId:", data.get("SessionId"))
    print("Version:", data.get("Version"))
    print("SessionTimeout:", data.get("SessionTimeout"))
    print()

    return data


# ============================================================
# Get Business Partners
# ============================================================

def get_business_partners():
    url = f"{BASE_URL}/BusinessPartners"

    params = {
        "$select": "CardCode,CardName,CardType",
        "$top": 5
    }

    response = session.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("=== Business Partners ===")

    for bp in data.get("value", []):
        print(
            bp.get("CardCode"),
            "|",
            bp.get("CardName"),
            "|",
            bp.get("CardType")
        )

    print()


# ============================================================
# Get Items
# ============================================================

def get_items():
    url = f"{BASE_URL}/Items"

    params = {
        "$select": "ItemCode,ItemName",
        "$top": 5
    }

    response = session.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("=== Items ===")

    for item in data.get("value", []):
        print(
            item.get("ItemCode"),
            "|",
            item.get("ItemName")
        )

    print()


# ============================================================
# Get recent Sales Orders
# ============================================================

def get_orders():
    url = f"{BASE_URL}/Orders"

    params = {
        "$select": (
            "DocEntry,"
            "DocNum,"
            "DocDate,"
            "CardCode,"
            "CardName,"
            "DocumentStatus,"
            "DocTotal"
        ),
        "$orderby": "DocEntry desc",
        "$top": 5
    }

    response = session.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("=== Recent Sales Orders ===")

    for order in data.get("value", []):
        print(json.dumps(
            order,
            indent=2,
            ensure_ascii=False
        ))

    print()


# ============================================================
# Get one Sales Order including lines
# ============================================================

def get_order(doc_entry):
    url = f"{BASE_URL}/Orders({doc_entry})"

    response = session.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print(f"=== Order DocEntry {doc_entry} ===")

    print("DocEntry:", data.get("DocEntry"))
    print("DocNum:", data.get("DocNum"))
    print("Customer:", data.get("CardCode"))
    print("Customer Name:", data.get("CardName"))
    print("Date:", data.get("DocDate"))
    print("Status:", data.get("DocumentStatus"))
    print()

    print("Order Lines:")

    for line in data.get("DocumentLines", []):
        print(
            line.get("LineNum"),
            "|",
            line.get("ItemCode"),
            "|",
            line.get("ItemDescription"),
            "| Qty:",
            line.get("Quantity"),
            "| Warehouse:",
            line.get("WarehouseCode")
        )

    print()


# ============================================================
# Logout
# ============================================================

def logout():
    response = session.post(
        f"{BASE_URL}/Logout",
        timeout=30
    )

    print("Logout status:", response.status_code)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    try:
        login()

        get_business_partners()

        get_items()

        get_orders()

        # 知道某个 SAP DocEntry 后再测试：
        # get_order(12345)

    finally:
        try:
            logout()
        except Exception:
            pass