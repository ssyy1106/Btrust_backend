import json
import sys
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from order_sync.config import get_config

settings = get_config()['sap_order_sync']
BASE_URL = settings['base_url'].rstrip('/')
VERIFY_SSL = settings.getboolean('verify_ssl')

# Compare with Odoo values. Preserve leading zeroes in barcodes.
TEST_PRODUCTS = [
    {'name': 'Coca-Cola Original Flavor', 'default_code': 'G000260', 'barcode': '00000000678290'},
    {'name': 'Fanta Orange', 'default_code': 'G000736', 'barcode': '00006700011023'},
    {'name': 'SamYang Chicken Ramen Cheese', 'default_code': 'G000812', 'barcode': '00880107314231'},
    {'name': 'Standard Delivery', 'default_code': 'Delivery_007', 'barcode': None},
]

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.verify = VERIFY_SSL


def get_json(path, params=None):
    response = session.get(f'{BASE_URL}/{path}', params=params, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        print('HTTP error:', response.status_code, response.text[:1000])
        raise
    return response.json()


def odata_quote(value):
    return str(value).replace("'", "''")


def login():
    response = session.post(
        f'{BASE_URL}/Login',
        json={
            'CompanyDB': settings['company_db'],
            'UserName': settings['username'],
            'Password': settings['password'],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    print('=== Login Success ===')
    print('Version:', data.get('Version'))
    print('SessionTimeout:', data.get('SessionTimeout'))
    print('(SessionId hidden)')


def get_business_partners():
    data = get_json('BusinessPartners', {'$select': 'CardCode,CardName,CardType', '$top': 20})
    print('\n=== Business Partners (first 20) ===')
    for bp in data.get('value', []):
        print(bp.get('CardCode'), '|', bp.get('CardName'), '|', bp.get('CardType'))


def get_items():
    data = get_json('Items', {'$select': 'ItemCode,ItemName,BarCode', '$top': 5})
    print('\n=== Items (first 5) ===')
    for item in data.get('value', []):
        print(item.get('ItemCode'), '|', item.get('ItemName'), '| barcode:', item.get('BarCode'))


def query_items(field, value):
    if not value:
        return []
    return get_json('Items', {
        '$select': 'ItemCode,ItemName,BarCode,SalesUnit,InventoryUOM',
        '$filter': f"{field} eq '{odata_quote(value)}'",
        '$top': 20,
    }).get('value', [])


def diagnose_product(product):
    print('\n' + '=' * 70)
    print('Odoo product:', product['name'])
    print('Odoo default_code:', product['default_code'])
    print('Odoo barcode:', product['barcode'])
    by_code = query_items('ItemCode', product['default_code'])
    by_barcode = query_items('BarCode', product['barcode'])
    print('SAP matches by ItemCode:', len(by_code))
    for item in by_code:
        print(' ', json.dumps(item, ensure_ascii=False))
    print('SAP matches by BarCode:', len(by_barcode))
    for item in by_barcode:
        print(' ', json.dumps(item, ensure_ascii=False))
    if not by_code and not by_barcode:
        print('NO MATCH: inspect SAP item master or create a verified mapping.')
    elif len(by_code) > 1 or len(by_barcode) > 1:
        print('WARNING: ambiguous match; do not select automatically.')
    elif by_code and by_barcode and by_code[0]['ItemCode'] != by_barcode[0]['ItemCode']:
        print('WARNING: default_code and barcode resolve to different SAP items.')
    else:
        chosen = (by_code or by_barcode)[0]
        print('CANDIDATE SAP ItemCode:', chosen['ItemCode'], '(verify UoM before syncing)')


def get_orders():
    data = get_json('Orders', {
        '$select': 'DocEntry,DocNum,DocDate,CardCode,CardName,DocumentStatus,DocTotal,NumAtCard',
        '$orderby': 'DocEntry desc', '$top': 10,
    })
    print('\n=== Recent 10 Sales Orders ===')
    for order in data.get('value', []):
        print(json.dumps(order, indent=2, ensure_ascii=False))


def get_order(doc_entry):
    data = get_json(f'Orders({int(doc_entry)})')
    print(f'\n=== Order DocEntry {doc_entry} ===')
    print('DocNum:', data.get('DocNum'), 'Customer:', data.get('CardCode'),
          'NumAtCard:', data.get('NumAtCard'))
    for line in data.get('DocumentLines', []):
        print('Line:', line.get('LineNum'), 'ItemCode:', line.get('ItemCode'),
              'Description:', line.get('ItemDescription'), 'Qty:', line.get('Quantity'),
              'UoMEntry:', line.get('UoMEntry'), 'Warehouse:', line.get('WarehouseCode'))


def logout():
    response = session.post(f'{BASE_URL}/Logout', timeout=30)
    print('\nLogout status:', response.status_code)

def get_sales_order_drafts():
    response = session.get(
        f"{BASE_URL}/Drafts",
        params={
            "$select": "DocEntry,DocNum,DocDate,CardCode,CardName,NumAtCard,DocObjectCode,DocTotal",
            "$filter": "DocObjectCode eq '17'",
            "$orderby": "DocEntry desc",
            "$top": 30,
        },
        timeout=30,
    )

    print("Status:", response.status_code)
    print("Response:", response.text[:5000])
    response.raise_for_status()

    return response.json().get("value", [])

def get_recent_drafts():
    response = session.get(
        f"{BASE_URL}/Drafts",
        params={
            "$select": (
                "DocEntry,DocNum,DocDate,CardCode,"
                "CardName,NumAtCard,DocObjectCode,DocTotal"
            ),
            "$orderby": "DocEntry desc",
            "$top": 100,
        },
        timeout=30,
    )

    print("HTTP:", response.status_code)
    response.raise_for_status()

    drafts = response.json().get("value", [])

    print("Total returned:", len(drafts))

    for draft in drafts:
        if draft.get("DocObjectCode") == "oOrders":
            print(
                "DocEntry:", draft.get("DocEntry"),
                "| Date:", draft.get("DocDate"),
                "| Customer:", draft.get("CardCode"),
                "| NumAtCard:", draft.get("NumAtCard"),
            )

    return drafts

def find_order_and_draft(odoo_order_name):
    escaped = odoo_order_name.replace("'", "''")

    for endpoint in ["Orders", "Drafts"]:
        response = session.get(
            f"{BASE_URL}/{endpoint}",
            params={
                "$select": (
                    "DocEntry,DocNum,CardCode,"
                    "NumAtCard,DocDate"
                ),
                "$filter": f"NumAtCard eq '{escaped}'",
                "$top": 20,
            },
            timeout=30,
        )

        print(f"\n=== {endpoint} ===")
        print("HTTP:", response.status_code)
        print("Response:", response.text[:5000])
        response.raise_for_status()

if __name__ == '__main__':
    logged_in = False
    try:
        login()
        logged_in = True
        get_business_partners()
        get_items()
        for product in TEST_PRODUCTS:
            try:
                diagnose_product(product)
            except requests.HTTPError as exc:
                print('Diagnostic failed:', exc)
                print('Check Items fields/permissions and Service Layer version.')
        get_orders()
        find_order_and_draft("ODOO-BT-89")
        # Uncomment after identifying a SAP DocEntry:
        # get_order(12345)
    finally:
        if logged_in:
            try:
                logout()
            except requests.RequestException as exc:
                print('Logout failed:', exc)
        session.close()
