import os
import ssl
import sys
from uuid import UUID
from typing import Any

import certifi
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from helper import verify_token
from graphqlschema.schema import UserInformation
from get_netsuite_token import get_access_token

load_dotenv()

router = APIRouter(prefix="/netsuite", tags=["NetSuite"])

ACCOUNT_ID = os.getenv("NETSUITE_ACCOUNT_ID", "").strip()
CLIENT_ID = os.getenv("NETSUITE_CLIENT_ID", "").strip()
CERTIFICATE_ID = os.getenv("NETSUITE_CERTIFICATE_ID", "").strip()
PRIVATE_KEY_FILE = os.getenv("NETSUITE_PRIVATE_KEY_FILE", "private.pem").strip()
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "").strip()
REQUESTS_CA_BUNDLE = os.getenv("REQUESTS_CA_BUNDLE", "").strip()
CURL_CA_BUNDLE = os.getenv("CURL_CA_BUNDLE", "").strip()
NETSUITE_CA_BUNDLE = os.getenv("NETSUITE_CA_BUNDLE", "").strip()

TOKEN_URL = (
    f"https://{ACCOUNT_ID}.suitetalk.api.netsuite.com"
    "/services/rest/auth/oauth2/v1/token"
)
SUITEQL_URL = (
    f"https://{ACCOUNT_ID}.suitetalk.api.netsuite.com"
    "/services/rest/query/v1/suiteql"
)
RECORD_URL = (
    f"https://{ACCOUNT_ID}.suitetalk.api.netsuite.com"
    "/services/rest/record/v1"
)


class BinTransferRequest(BaseModel):
    item_id: str
    from_bin_id: str
    to_bin_id: str
    lot_number: str
    quantity: float = Field(gt=0)
    memo: str | None = None
    externalId: UUID


def _escape_suiteql_literal(value: str) -> str:
    return value.replace("'", "''")


def _get_httpx_verify() -> str:
    return (
        NETSUITE_CA_BUNDLE
        or SSL_CERT_FILE
        or REQUESTS_CA_BUNDLE
        or CURL_CA_BUNDLE
        or certifi.where()
    )


def _build_ssl_debug_info() -> dict[str, Any]:
    verify_value = _get_httpx_verify()
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "verify_path": verify_value,
        "verify_path_exists": os.path.exists(verify_value) if isinstance(verify_value, str) else None,
        "certifi_path": certifi.where(),
        "ssl_cert_file": SSL_CERT_FILE or None,
        "requests_ca_bundle": REQUESTS_CA_BUNDLE or None,
        "curl_ca_bundle": CURL_CA_BUNDLE or None,
        "netsuite_ca_bundle": NETSUITE_CA_BUNDLE or None,
        "openssl_default_paths": {
            "cafile": ssl.get_default_verify_paths().cafile,
            "capath": ssl.get_default_verify_paths().capath,
            "openssl_cafile": ssl.get_default_verify_paths().openssl_cafile,
            "openssl_capath": ssl.get_default_verify_paths().openssl_capath,
        },
    }


async def _execute_suiteql(
    query: str,
    access_token: str,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": "transient",
        "Content-Type": "application/json",
    }
    verify = _get_httpx_verify()
    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    try:
        async with httpx.AsyncClient(timeout=30, verify=verify) as client:
            response = await client.post(
                SUITEQL_URL,
                headers=headers,
                params=params or None,
                json={"q": " ".join(query.split())},
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except ValueError:
            detail = exc.response.text
        raise HTTPException(
            status_code=502,
            detail={"message": "NetSuite SuiteQL query failed.", "netsuite_error": detail},
        ) from exc
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to connect to NetSuite SuiteQL endpoint.",
                "error": str(exc),
                "ssl_debug": _build_ssl_debug_info(),
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to NetSuite SuiteQL endpoint: {exc}") from exc

    return response.json()


async def _post_record(
    record_type: str,
    payload: dict[str, Any],
    access_token: str,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": "transient",
        "Content-Type": "application/json",
    }
    verify = _get_httpx_verify()

    try:
        async with httpx.AsyncClient(timeout=30, verify=verify) as client:
            response = await client.post(
                f"{RECORD_URL}/{record_type}",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except ValueError:
            detail = exc.response.text
        raise HTTPException(
            status_code=502,
            detail={"message": f"NetSuite {record_type} create failed.", "netsuite_error": detail},
        ) from exc
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"Failed to connect to NetSuite {record_type} endpoint.",
                "error": str(exc),
                "ssl_debug": _build_ssl_debug_info(),
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to NetSuite {record_type} endpoint: {exc}") from exc

    result: dict[str, Any] = {
        "status_code": response.status_code,
        "location": response.headers.get("Location"),
    }
    if response.content:
        try:
            result["body"] = response.json()
        except ValueError:
            result["body"] = response.text
    return result


def _require_internal_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or not normalized.isdigit():
        raise HTTPException(status_code=400, detail=f"{field_name} must be a NetSuite internal ID.")
    return normalized


# @router.get("/diagnostics")
# async def get_netsuite_diagnostics(
#     _user: UserInformation = Depends(verify_token),
# ):
#     return _build_ssl_debug_info()


@router.post("/bin-transfer")
async def bin_transfer(
    req: BinTransferRequest,
    _user: UserInformation = Depends(verify_token),
):
    item_id = _require_internal_id(req.item_id, "item_id")
    from_bin_id = _require_internal_id(req.from_bin_id, "from_bin_id")
    to_bin_id = _require_internal_id(req.to_bin_id, "to_bin_id")
    lot_number = req.lot_number.strip()
    if not lot_number:
        raise HTTPException(status_code=400, detail="lot_number cannot be empty.")
    if from_bin_id == to_bin_id:
        raise HTTPException(status_code=400, detail="from_bin_id and to_bin_id cannot be the same.")

    access_token = get_access_token()["access_token"]
    external_id = str(req.externalId)
    escaped_external_id = _escape_suiteql_literal(external_id)
    existing_payload = await _execute_suiteql(
        f"""
        SELECT id, tranid, externalid
        FROM transaction
        WHERE externalid = '{escaped_external_id}'
        ORDER BY id DESC
        """,
        access_token,
        limit=1,
    )
    existing_items = existing_payload.get("items", [])
    if existing_items:
        return {
            "success": True,
            "created": False,
            "message": "Bin transfer already exists for this externalId.",
            "externalId": external_id,
            "existing_record": existing_items[0],
        }

    escaped_lot_number = _escape_suiteql_literal(lot_number)
    balance_payload = await _execute_suiteql(
        f"""
        SELECT
            ib.item,
            i.itemid,
            ib.location,
            l.name AS location_name,
            l.subsidiary AS subsidiary_id,
            BUILTIN.DF(l.subsidiary) AS subsidiary_name,
            ib.binnumber AS bin_internal_id,
            b.binnumber AS binnumber,
            ib.inventorynumber,
            inv.inventorynumber AS lot_number,
            ib.quantityonhand,
            ib.quantityavailable
        FROM inventorybalance ib
        JOIN item i
            ON i.id = ib.item
        LEFT JOIN location l
            ON l.id = ib.location
        LEFT JOIN bin b
            ON b.id = ib.binnumber
        LEFT JOIN inventorynumber inv
            ON inv.id = ib.inventorynumber
        WHERE ib.item = {item_id}
          AND ib.binnumber = {from_bin_id}
          AND inv.inventorynumber = '{escaped_lot_number}'
        ORDER BY ib.location
        """,
        access_token,
    )
    balance_items = balance_payload.get("items", [])
    if not balance_items:
        raise HTTPException(status_code=404, detail="No inventory found for the given item, from bin, and lot number.")

    location_ids = {str(item.get("location")) for item in balance_items if item.get("location") is not None}
    subsidiary_ids = {str(item.get("subsidiary_id")) for item in balance_items if item.get("subsidiary_id") is not None}
    inventory_number_ids = {str(item.get("inventorynumber")) for item in balance_items if item.get("inventorynumber") is not None}
    if len(location_ids) != 1:
        raise HTTPException(status_code=400, detail="Expected inventory to resolve to exactly one location.")
    if len(subsidiary_ids) != 1:
        raise HTTPException(status_code=400, detail="Expected inventory to resolve to exactly one subsidiary.")
    if len(inventory_number_ids) != 1:
        raise HTTPException(status_code=400, detail="Expected lot_number to resolve to exactly one inventory number.")

    quantity_available = sum(float(item.get("quantityavailable") or 0) for item in balance_items)
    if req.quantity > quantity_available:
        raise HTTPException(
            status_code=400,
            detail=f"Quantity exceeds available quantity. requested={req.quantity}, available={quantity_available}",
        )

    from_location_id = next(iter(location_ids))
    subsidiary_id = next(iter(subsidiary_ids))
    inventory_number_id = next(iter(inventory_number_ids))

    to_bin_payload = await _execute_suiteql(
        f"""
        SELECT
            b.id,
            b.binnumber AS binnumber,
            b.location,
            l.name AS location_name
        FROM bin b
        LEFT JOIN location l
            ON l.id = b.location
        WHERE b.id = {to_bin_id}
        """,
        access_token,
        limit=1,
    )
    to_bin_items = to_bin_payload.get("items", [])
    if not to_bin_items:
        raise HTTPException(status_code=404, detail="to_bin_id not found.")

    to_bin_location_id = str(to_bin_items[0].get("location") or "")
    if not to_bin_location_id:
        raise HTTPException(status_code=400, detail="to_bin_id does not have a location.")
    if to_bin_location_id != from_location_id:
        raise HTTPException(
            status_code=400,
            detail="from_bin_id and to_bin_id must belong to the same location for bin transfer.",
        )

    payload = {
        "externalId": external_id,
        "subsidiary": {"id": subsidiary_id},
        "location": {"id": from_location_id},
        "memo": req.memo,
        "inventory": {
            "items": [
                {
                    "item": {"id": item_id},
                    "quantity": req.quantity,
                    "inventoryDetail": {
                        "inventoryAssignment": {
                            "items": [
                                {
                                    "binNumber": {"id": from_bin_id},
                                    "toBinNumber": {"id": to_bin_id},
                                    "issueInventoryNumber": {"id": inventory_number_id},
                                    "quantity": req.quantity,
                                }
                            ]
                        }
                    },
                }
            ]
        },
    }
    if req.memo is None:
        payload.pop("memo")

    result = await _post_record("binTransfer", payload, access_token)
    return {
        "success": True,
        "created": True,
        "subsidiary_id": subsidiary_id,
        "validated_quantity": quantity_available,
        "netsuite": result,
    }


@router.get("/lot")
async def get_all_lots(
    limit: int = Query(50, ge=1, le=500, description="每页条数，默认50，最大500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页"),
    _user: UserInformation = Depends(verify_token),
):
    access_token = get_access_token()["access_token"]

    count_payload = await _execute_suiteql(
        "SELECT COUNT(*) AS total FROM inventorynumber",
        access_token,
    )
    total_items = count_payload.get("items", [])
    total = int(total_items[0].get("total", 0)) if total_items else 0

    payload = await _execute_suiteql(
        "SELECT * FROM inventorynumber ORDER BY id",
        access_token,
        limit=limit,
        offset=offset,
    )
    items = payload.get("items", [])

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/bin")
async def get_all_bins(
    q: str | None = Query(None, description="模糊搜索 binnumber 或 location_name"),
    limit: int = Query(50, ge=1, le=9999, description="每页条数，默认50，最大9999"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页"),
    _user: UserInformation = Depends(verify_token),
):
    access_token = get_access_token()["access_token"]
    where_clause = ""
    if q and q.strip():
        escaped_q = _escape_suiteql_literal(q.strip())
        where_clause = (
            f"WHERE LOWER(b.binnumber) LIKE LOWER('%{escaped_q}%') "
            f"OR LOWER(l.name) LIKE LOWER('%{escaped_q}%')"
        )

    count_payload = await _execute_suiteql(
        f"""
        SELECT COUNT(*) AS total
        FROM bin b
        LEFT JOIN location l
            ON l.id = b.location
        {where_clause}
        """,
        access_token,
    )
    total_items = count_payload.get("items", [])
    total = int(total_items[0].get("total", 0)) if total_items else 0

    payload = await _execute_suiteql(
        f"""
        SELECT
            b.id,
            b.binnumber AS binnumber,
            b.location,
            l.name AS location_name
        FROM bin b
        LEFT JOIN location l
            ON l.id = b.location
        {where_clause}
        ORDER BY b.binnumber, b.id
        """,
        access_token,
        limit=limit,
        offset=offset,
    )
    items = payload.get("items", [])

    return {
        "q": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/lot/{lot_number}")
async def get_lot_inventory(
    lot_number: str,
    _user: UserInformation = Depends(verify_token),
):
    escaped_lot_number = _escape_suiteql_literal(lot_number.strip())
    if not escaped_lot_number:
        raise HTTPException(status_code=400, detail="lot_number cannot be empty.")

    suiteql = f"""
        SELECT
            ib.item,
            i.itemid,
            i.displayname,
            i.upccode,
            i.itemtype,
            i.custitem_es_itemsize,
            i.purchasedescription,
            i.unitstype,
            BUILTIN.DF(i.unitstype) AS unitstype_name,
            i.stockunit,
            BUILTIN.DF(i.stockunit) AS stockunit_name,
            i.saleunit,
            BUILTIN.DF(i.saleunit) AS saleunit_name,
            i.purchaseunit,
            BUILTIN.DF(i.purchaseunit) AS purchaseunit_name,
            i.isinactive,
            ib.location,
            l.name AS location_name,
            ib.binnumber AS bin_internal_id,
            b.binnumber AS binnumber,
            ib.inventorynumber,
            inv.inventorynumber AS lot_number,
            ib.quantityonhand,
            ib.quantityavailable
        FROM inventorybalance ib
        JOIN item i
            ON i.id = ib.item
        LEFT JOIN location l
            ON l.id = ib.location
        LEFT JOIN bin b
            ON b.id = ib.binnumber
        LEFT JOIN inventorynumber inv
            ON inv.id = ib.inventorynumber
        WHERE inv.inventorynumber = '{escaped_lot_number}'
        ORDER BY i.itemid, l.name, b.binnumber
    """

    access_token = get_access_token()["access_token"]
    payload = await _execute_suiteql(suiteql, access_token)
    items = payload.get("items", [])
    return {
        "lot_number": lot_number,
        "count": len(items),
        "items": items,
    }
