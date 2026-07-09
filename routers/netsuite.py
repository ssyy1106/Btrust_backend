import os
import ssl
import sys
import json
from uuid import UUID
from typing import Any

import certifi
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from pydantic import BaseModel, Field

from helper import verify_token, log_and_save
from graphqlschema.schema import UserInformation
from get_netsuite_token import get_access_token

load_dotenv()

ACCOUNT_ID = os.getenv("NETSUITE_ACCOUNT_ID", "").strip()
CLIENT_ID = os.getenv("NETSUITE_CLIENT_ID", "").strip()
CERTIFICATE_ID = os.getenv("NETSUITE_CERTIFICATE_ID", "").strip()
PRIVATE_KEY_FILE = os.getenv("NETSUITE_PRIVATE_KEY_FILE", "private.pem").strip()
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "").strip()
REQUESTS_CA_BUNDLE = os.getenv("REQUESTS_CA_BUNDLE", "").strip()
CURL_CA_BUNDLE = os.getenv("CURL_CA_BUNDLE", "").strip()
NETSUITE_CA_BUNDLE = os.getenv("NETSUITE_CA_BUNDLE", "").strip()
API_KEYS = {
    key.strip()
    for key in os.getenv("API_KEYS", "").split(",")
    if key.strip()
}

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


def _log_netsuite(level: str, event: str, **context: Any) -> None:
    safe_context = {key: value for key, value in context.items() if value is not None}
    if safe_context:
        message = f"[netsuite] {event} | {json.dumps(safe_context, ensure_ascii=False, default=str)}"
    else:
        message = f"[netsuite] {event}"
    log_and_save(level, message)


def verify_netsuite_api_key(x_api_key: str | None = Header(None)):
    if not x_api_key:
        _log_netsuite("WARNING", "missing_api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing x-api-key header.",
        )
    if x_api_key not in API_KEYS:
        _log_netsuite("WARNING", "invalid_api_key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid x-api-key.",
        )
    return x_api_key


router = APIRouter(
    prefix="/netsuite",
    tags=["NetSuite"],
    dependencies=[Depends(verify_netsuite_api_key)],
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


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _load_unit_conversions(
    items: list[dict[str, Any]],
    access_token: str,
) -> dict[str, dict[str, Any]]:
    unit_ids = {
        str(item.get(field)).strip()
        for item in items
        for field in ("stockunit", "saleunit", "purchaseunit")
        if item.get(field) is not None and str(item.get(field)).strip()
    }
    if not unit_ids:
        return {}

    suiteql = f"""
        SELECT
            u.internalid AS unit_internal_id,
            u.unitname AS unit_name,
            u.abbreviation AS unit_abbreviation,
            u.pluralabbreviation AS unit_plural_abbreviation,
            u.conversionrate,
            u.baseunit,
            u.unitstype,
            BUILTIN.DF(u.unitstype) AS unitstype_name
        FROM UnitsTypeUom u
        WHERE u.internalid IN ({", ".join(sorted(unit_ids))})
    """
    payload = await _execute_suiteql(suiteql, access_token)
    return {
        str(unit.get("unit_internal_id")): unit
        for unit in payload.get("items", [])
        if unit.get("unit_internal_id") is not None
    }


def _with_unit_quantities(
    item: dict[str, Any],
    unit_conversions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched_item = dict(item)
    quantity_available = _parse_float(enriched_item.get("quantityavailable"))
    quantity_on_hand = _parse_float(enriched_item.get("quantityonhand"))

    for unit_field in ("purchaseunit", "saleunit", "stockunit"):
        unit_id = enriched_item.get(unit_field)
        if unit_id is None:
            continue
        conversion = unit_conversions.get(str(unit_id))
        prefix = unit_field.replace("unit", "")
        if not conversion:
            enriched_item[f"{prefix}unit_conversionrate"] = None
            enriched_item[f"quantityavailable_{prefix}units"] = None
            enriched_item[f"quantityonhand_{prefix}units"] = None
            continue

        conversion_rate = _parse_float(conversion.get("conversionrate"))
        enriched_item[f"{prefix}unit_config"] = conversion
        enriched_item[f"{prefix}unit_conversionrate"] = conversion_rate
        enriched_item[f"quantityavailable_{prefix}units"] = (
            quantity_available / conversion_rate
            if conversion_rate and quantity_available is not None
            else None
        )
        enriched_item[f"quantityonhand_{prefix}units"] = (
            quantity_on_hand / conversion_rate
            if conversion_rate and quantity_on_hand is not None
            else None
        )
    return enriched_item


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

    _log_netsuite(
        "INFO",
        "suiteql_request",
        limit=limit,
        offset=offset,
        query=" ".join(query.split()),
    )

    try:
        async with httpx.AsyncClient(timeout=30, verify=verify) as client:
            response = await client.post(
                SUITEQL_URL,
                headers=headers,
                params=params or None,
                json={"q": " ".join(query.split())},
            )
        response.raise_for_status()
        payload = response.json()
        _log_netsuite(
            "INFO",
            "suiteql_success",
            status_code=response.status_code,
            count=len(payload.get("items", [])) if isinstance(payload, dict) else None,
            has_links=isinstance(payload, dict) and bool(payload.get("links")),
        )
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except ValueError:
            detail = exc.response.text
        _log_netsuite(
            "ERROR",
            "suiteql_http_error",
            status_code=exc.response.status_code,
            detail=detail,
        )
        raise HTTPException(
            status_code=502,
            detail={"message": "NetSuite SuiteQL query failed.", "netsuite_error": detail},
        ) from exc
    except httpx.ConnectError as exc:
        _log_netsuite("ERROR", "suiteql_connect_error", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to connect to NetSuite SuiteQL endpoint.",
                "error": str(exc),
                "ssl_debug": _build_ssl_debug_info(),
            },
        ) from exc
    except httpx.HTTPError as exc:
        _log_netsuite("ERROR", "suiteql_request_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to connect to NetSuite SuiteQL endpoint: {exc}") from exc

    return payload


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

    _log_netsuite(
        "INFO",
        "record_create_request",
        record_type=record_type,
        payload=payload,
    )

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
        _log_netsuite(
            "ERROR",
            "record_create_http_error",
            record_type=record_type,
            status_code=exc.response.status_code,
            detail=detail,
        )
        raise HTTPException(
            status_code=502,
            detail={"message": f"NetSuite {record_type} create failed.", "netsuite_error": detail},
        ) from exc
    except httpx.ConnectError as exc:
        _log_netsuite(
            "ERROR",
            "record_create_connect_error",
            record_type=record_type,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"Failed to connect to NetSuite {record_type} endpoint.",
                "error": str(exc),
                "ssl_debug": _build_ssl_debug_info(),
            },
        ) from exc
    except httpx.HTTPError as exc:
        _log_netsuite(
            "ERROR",
            "record_create_request_error",
            record_type=record_type,
            error=str(exc),
        )
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
    _log_netsuite(
        "INFO",
        "record_create_success",
        record_type=record_type,
        status_code=result.get("status_code"),
        location=result.get("location"),
    )
    return result


def _require_internal_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or not normalized.isdigit():
        raise HTTPException(status_code=400, detail=f"{field_name} must be a NetSuite internal ID.")
    return normalized


def _build_item_lookup_filters(value: str) -> tuple[str, str]:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="item_id cannot be empty.")
    if normalized.isdigit():
        return (f"i.id = {normalized}", f"ib.item = {normalized}")

    escaped_item_id = _escape_suiteql_literal(normalized)
    return (f"i.itemid = '{escaped_item_id}'", f"i.itemid = '{escaped_item_id}'")


def _group_lots_with_bins(raw_lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_lots: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}

    for row in raw_lots:
        lot_key = (
            row.get("item"),
            row.get("inventorynumber"),
            row.get("location"),
            row.get("expirationdate"),
        )
        quantity_on_hand = _parse_float(row.get("quantityonhand")) or 0.0
        quantity_available = _parse_float(row.get("quantityavailable")) or 0.0

        lot_entry = grouped_lots.get(lot_key)
        if lot_entry is None:
            lot_entry = {
                "item": row.get("item"),
                "location": row.get("location"),
                "location_name": row.get("location_name"),
                "inventorynumber": row.get("inventorynumber"),
                "lot_number": row.get("lot_number"),
                "expirationdate": row.get("expirationdate"),
                "quantityonhand": quantity_on_hand,
                "quantityavailable": quantity_available,
                "bins": [],
            }
            grouped_lots[lot_key] = lot_entry
        else:
            lot_entry["quantityonhand"] += quantity_on_hand
            lot_entry["quantityavailable"] += quantity_available

        lot_entry["bins"].append(
            {
                "bin_internal_id": row.get("bin_internal_id"),
                "binnumber": row.get("binnumber"),
                "quantityonhand": row.get("quantityonhand"),
                "quantityavailable": row.get("quantityavailable"),
            }
        )

    return list(grouped_lots.values())


# @router.get("/diagnostics")
# async def get_netsuite_diagnostics(
#     _user: UserInformation = Depends(verify_token),
# ):
#     return _build_ssl_debug_info()


@router.post("/bin-transfer")
async def bin_transfer(
    req: BinTransferRequest
):
    _log_netsuite(
        "INFO",
        "bin_transfer_started",
        item_id=req.item_id,
        from_bin_id=req.from_bin_id,
        to_bin_id=req.to_bin_id,
        lot_number=req.lot_number,
        quantity=req.quantity,
        externalId=req.externalId,
    )
    item_id = _require_internal_id(req.item_id, "item_id")
    from_bin_id = _require_internal_id(req.from_bin_id, "from_bin_id")
    to_bin_id = _require_internal_id(req.to_bin_id, "to_bin_id")
    lot_number = req.lot_number.strip()
    if not lot_number:
        _log_netsuite("WARNING", "bin_transfer_empty_lot_number", externalId=req.externalId)
        raise HTTPException(status_code=400, detail="lot_number cannot be empty.")
    if from_bin_id == to_bin_id:
        _log_netsuite(
            "WARNING",
            "bin_transfer_same_bin",
            from_bin_id=from_bin_id,
            to_bin_id=to_bin_id,
            externalId=req.externalId,
        )
        raise HTTPException(status_code=400, detail="from_bin_id and to_bin_id cannot be the same.")

    access_token = get_access_token()["access_token"]
    _log_netsuite("INFO", "netsuite_access_token_acquired", action="bin_transfer")
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
        _log_netsuite(
            "INFO",
            "bin_transfer_duplicate_external_id",
            externalId=external_id,
            existing_record=existing_items[0],
        )
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
            inv.expirationdate,
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
        _log_netsuite(
            "WARNING",
            "bin_transfer_inventory_not_found",
            item_id=item_id,
            from_bin_id=from_bin_id,
            lot_number=lot_number,
            externalId=external_id,
        )
        raise HTTPException(status_code=404, detail="No inventory found for the given item, from bin, and lot number.")

    location_ids = {str(item.get("location")) for item in balance_items if item.get("location") is not None}
    subsidiary_ids = {str(item.get("subsidiary_id")) for item in balance_items if item.get("subsidiary_id") is not None}
    inventory_number_ids = {str(item.get("inventorynumber")) for item in balance_items if item.get("inventorynumber") is not None}
    if len(location_ids) != 1:
        _log_netsuite("WARNING", "bin_transfer_multiple_locations", externalId=external_id, location_ids=list(location_ids))
        raise HTTPException(status_code=400, detail="Expected inventory to resolve to exactly one location.")
    if len(subsidiary_ids) != 1:
        _log_netsuite("WARNING", "bin_transfer_multiple_subsidiaries", externalId=external_id, subsidiary_ids=list(subsidiary_ids))
        raise HTTPException(status_code=400, detail="Expected inventory to resolve to exactly one subsidiary.")
    if len(inventory_number_ids) != 1:
        _log_netsuite(
            "WARNING",
            "bin_transfer_multiple_inventory_numbers",
            externalId=external_id,
            inventory_number_ids=list(inventory_number_ids),
        )
        raise HTTPException(status_code=400, detail="Expected lot_number to resolve to exactly one inventory number.")

    quantity_available = sum(float(item.get("quantityavailable") or 0) for item in balance_items)
    _log_netsuite(
        "INFO",
        "bin_transfer_inventory_validated",
        externalId=external_id,
        matched_rows=len(balance_items),
        quantity_available=quantity_available,
    )
    if req.quantity > quantity_available:
        _log_netsuite(
            "WARNING",
            "bin_transfer_quantity_exceeded",
            externalId=external_id,
            requested_quantity=req.quantity,
            available_quantity=quantity_available,
        )
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
        _log_netsuite("WARNING", "bin_transfer_to_bin_not_found", externalId=external_id, to_bin_id=to_bin_id)
        raise HTTPException(status_code=404, detail="to_bin_id not found.")

    to_bin_location_id = str(to_bin_items[0].get("location") or "")
    if not to_bin_location_id:
        _log_netsuite("WARNING", "bin_transfer_to_bin_missing_location", externalId=external_id, to_bin_id=to_bin_id)
        raise HTTPException(status_code=400, detail="to_bin_id does not have a location.")
    if to_bin_location_id != from_location_id:
        _log_netsuite(
            "WARNING",
            "bin_transfer_location_mismatch",
            externalId=external_id,
            from_location_id=from_location_id,
            to_bin_location_id=to_bin_location_id,
        )
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

    _log_netsuite(
        "INFO",
        "bin_transfer_payload_ready",
        externalId=external_id,
        subsidiary_id=subsidiary_id,
        from_location_id=from_location_id,
        inventory_number_id=inventory_number_id,
    )
    result = await _post_record("binTransfer", payload, access_token)
    _log_netsuite(
        "INFO",
        "bin_transfer_completed",
        externalId=external_id,
        validated_quantity=quantity_available,
        netsuite_status_code=result.get("status_code"),
        netsuite_location=result.get("location"),
    )
    return {
        "success": True,
        "created": True,
        "subsidiary_id": subsidiary_id,
        "validated_quantity": quantity_available,
        "netsuite": result,
    }


@router.get("/lot")
async def get_all_lots(
    location_id: str | None = Query(None, description="按 location internal id 筛选"),
    limit: int = Query(50, ge=1, le=500, description="每页条数，默认50，最大500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页")
):
    _log_netsuite("INFO", "get_all_lots_started", location_id=location_id, limit=limit, offset=offset)
    access_token = get_access_token()["access_token"]
    normalized_location_id: str | None = None
    if location_id is not None and location_id.strip():
        normalized_location_id = _require_internal_id(location_id, "location_id")

    if normalized_location_id is None:
        count_query = "SELECT COUNT(*) AS total FROM inventorynumber"
        data_query = "SELECT * FROM inventorynumber ORDER BY id"
    else:
        count_query = f"""
        SELECT COUNT(DISTINCT inv.id) AS total
        FROM inventorynumber inv
        JOIN inventorybalance ib
            ON ib.inventorynumber = inv.id
        WHERE ib.location = {normalized_location_id}
        """
        data_query = f"""
        SELECT DISTINCT inv.*
        FROM inventorynumber inv
        JOIN inventorybalance ib
            ON ib.inventorynumber = inv.id
        WHERE ib.location = {normalized_location_id}
        ORDER BY inv.id
        """

    count_payload = await _execute_suiteql(count_query, access_token)
    total_items = count_payload.get("items", [])
    total = int(total_items[0].get("total", 0)) if total_items else 0

    payload = await _execute_suiteql(data_query, access_token, limit=limit, offset=offset)
    items = payload.get("items", [])

    _log_netsuite("INFO", "get_all_lots_completed", location_id=location_id, total=total, count=len(items))

    return {
        "location_id": location_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/bin")
async def get_all_bins(
    binnumber: str | None = Query(None, description="模糊搜索 binnumber"),
    location_name: str | None = Query(None, description="模糊搜索 location_name"),
    location_id: str | None = Query(None, description="按 location internal id 筛选"),
    limit: int = Query(50, ge=1, le=9999, description="每页条数，默认50，最大9999"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页")
):
    _log_netsuite(
        "INFO",
        "get_all_bins_started",
        binnumber=binnumber,
        location_name=location_name,
        location_id=location_id,
        limit=limit,
        offset=offset,
    )
    access_token = get_access_token()["access_token"]
    filters: list[str] = []
    if binnumber and binnumber.strip():
        escaped_binnumber = _escape_suiteql_literal(binnumber.strip())
        filters.append(f"LOWER(b.binnumber) LIKE LOWER('%{escaped_binnumber}%')")
    if location_name and location_name.strip():
        escaped_location_name = _escape_suiteql_literal(location_name.strip())
        filters.append(f"LOWER(l.name) LIKE LOWER('%{escaped_location_name}%')")
    if location_id is not None and location_id.strip():
        normalized_location_id = _require_internal_id(location_id, "location_id")
        filters.append(f"b.location = {normalized_location_id}")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

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

    _log_netsuite("INFO", "get_all_bins_completed", total=total, count=len(items), location_id=location_id)

    return {
        "binnumber": binnumber,
        "location_name": location_name,
        "location_id": location_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/location")
async def get_all_locations(
    limit: int = Query(50, ge=1, le=500, description="得到所有location 最多一次500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页")
):
    _log_netsuite("INFO", "get_all_locations_started", limit=limit, offset=offset)
    access_token = get_access_token()["access_token"]

    count_payload = await _execute_suiteql(
        "SELECT COUNT(*) AS total FROM location",
        access_token,
    )
    total_items = count_payload.get("items", [])
    total = int(total_items[0].get("total", 0)) if total_items else 0

    payload = await _execute_suiteql(
        "SELECT * FROM location ORDER BY id",
        access_token,
        limit=limit,
        offset=offset,
    )
    items = payload.get("items", [])

    _log_netsuite("INFO", "get_all_locations_completed", total=total, count=len(items))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/item/{item_id}")
async def get_item_inventory(
    item_id: str,
    location_id: str | None = Query(None, description="按 location internal id 筛选")
):
    _log_netsuite("INFO", "get_item_inventory_started", item_id=item_id, location_id=location_id)
    normalized_item_id = item_id.strip()
    item_filter, lot_filter = _build_item_lookup_filters(item_id)

    location_filter = ""
    if location_id is not None and location_id.strip():
        normalized_location_id = _require_internal_id(location_id, "location_id")
        location_filter = f" AND ib.location = {normalized_location_id}"

    access_token = get_access_token()["access_token"]

    item_query = f"""
        SELECT
            i.id,
            i.itemid,
            i.displayname,
            i.upccode,
            i.itemtype,
            i.custitem_es_itemsize,
            i.custitem_es_itempacking AS packing,
            i.purchasedescription,
            i.unitstype,
            BUILTIN.DF(i.unitstype) AS unitstype_name,
            i.stockunit,
            BUILTIN.DF(i.stockunit) AS stockunit_name,
            i.saleunit,
            BUILTIN.DF(i.saleunit) AS saleunit_name,
            i.purchaseunit,
            BUILTIN.DF(i.purchaseunit) AS purchaseunit_name,
            i.isinactive
        FROM item i
        WHERE {item_filter}
    """
    item_payload = await _execute_suiteql(item_query, access_token, limit=1)
    item_items = item_payload.get("items", [])
    if not item_items:
        _log_netsuite("WARNING", "get_item_inventory_item_not_found", item_id=normalized_item_id)
        raise HTTPException(status_code=404, detail="item_id not found.")

    item_info = item_items[0]
    lot_query = f"""
        SELECT
            ib.item,
            ib.location,
            l.name AS location_name,
            ib.binnumber AS bin_internal_id,
            b.binnumber AS binnumber,
            ib.inventorynumber,
            inv.inventorynumber AS lot_number,
            inv.expirationdate,
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
        WHERE {lot_filter}
        {location_filter}
        ORDER BY inv.expirationdate, inv.inventorynumber, l.name, b.binnumber
    """
    lot_payload = await _execute_suiteql(lot_query, access_token)
    raw_lots = lot_payload.get("items", [])
    try:
        unit_conversions = await _load_unit_conversions([item_info], access_token)
    except HTTPException:
        _log_netsuite(
            "WARNING",
            "get_item_inventory_unit_conversion_failed",
            item_id=normalized_item_id,
            location_id=location_id,
        )
        unit_conversions = {}

    item_info = _with_unit_quantities(item_info, unit_conversions)
    lots = _group_lots_with_bins(raw_lots)
    _log_netsuite(
        "INFO",
        "get_item_inventory_completed",
        item_id=normalized_item_id,
        location_id=location_id,
        lot_count=len(lots),
    )
    return {
        "item_id": normalized_item_id,
        "location_id": location_id,
        "item": item_info,
        "lots": lots,
    }


@router.get("/lot/{lot_number}")
async def get_lot_inventory(
    lot_number: str,
    location_id: str | None = Query(None, description="按 location internal id 筛选")
):
    _log_netsuite("INFO", "get_lot_inventory_started", lot_number=lot_number, location_id=location_id)
    escaped_lot_number = _escape_suiteql_literal(lot_number.strip())
    if not escaped_lot_number:
        _log_netsuite("WARNING", "get_lot_inventory_empty_lot_number", location_id=location_id)
        raise HTTPException(status_code=400, detail="lot_number cannot be empty.")
    location_filter = ""
    if location_id is not None and location_id.strip():
        normalized_location_id = _require_internal_id(location_id, "location_id")
        location_filter = f" AND ib.location = {normalized_location_id}"

    suiteql = f"""
        SELECT
            ib.item,
            i.itemid,
            i.displayname,
            i.upccode,
            i.itemtype,
            i.custitem_es_itemsize,
            i.custitem_es_itempacking AS packing,
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
            inv.expirationdate,
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
        {location_filter}
        ORDER BY i.itemid, l.name, b.binnumber
    """

    access_token = get_access_token()["access_token"]
    payload = await _execute_suiteql(suiteql, access_token)
    raw_items = payload.get("items", [])
    try:
        unit_conversions = await _load_unit_conversions(raw_items, access_token)
    except HTTPException:
        _log_netsuite("WARNING", "get_lot_inventory_unit_conversion_failed", lot_number=lot_number, location_id=location_id)
        unit_conversions = {}
    items = [_with_unit_quantities(item, unit_conversions) for item in raw_items]
    _log_netsuite("INFO", "get_lot_inventory_completed", lot_number=lot_number, location_id=location_id, count=len(items))
    return {
        "lot_number": lot_number,
        "location_id": location_id,
        "count": len(items),
        "items": items,
    }
