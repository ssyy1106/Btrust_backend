import logging
import xmlrpc.client

import requests

from celery_app import celery_app
from . import db
from .config import get_config
from .odoo import OdooClient
from .sap import SapClient

logger = logging.getLogger(__name__)


@celery_app.task(name="order_sync.poll_odoo_orders")
def poll_odoo_orders():
    client = OdooClient()
    inserted = 0
    try:
        for order in client.iter_today_orders():
            inserted += db.insert_order(
                client.settings["db"], order,
                get_config()["celery_order_sync"].getint("max_attempts"),
            )
    finally:
        client.close()
    logger.info("Odoo poll finished: %s new orders", inserted)
    return {"inserted": inserted}


@celery_app.task(name="order_sync.publish_outbox")
def publish_outbox():
    db.enqueue_due_retries()
    published = 0
    settings = get_config()["celery_order_sync"]
    for _ in range(settings.getint("publish_batch_size")):
        event = db.claim_outbox()
        if event is None:
            break
        try:
            sync_order_to_sap.apply_async(
                kwargs={"order_sync_id": event["order_sync_id"]},
                queue=settings["queue"], routing_key=settings["queue"],
                delivery_mode=2, retry=False,
            )
        except Exception as exc:
            db.finish_publish(event, error=f"{type(exc).__name__}: {exc}")
            logger.warning("Outbox %s publish failed", event["id"])
        else:
            # Keep DB failures outside the broker-error handler: sending already succeeded.
            db.finish_publish(event)
            published += 1
    return {"published": published}


def failure_status(order, exc, post_started):
    # A timeout/5xx after POST may already have created the SAP order.
    # Do not automatically POST again without confirmation.
    if post_started:
        return "review"
    if isinstance(exc, (ValueError, xmlrpc.client.Fault)):
        return "review"
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        if code not in {408, 429} and code < 500:
            return "review"
    return "retry" if order["attempt_count"] < order["max_attempts"] else "review"


@celery_app.task(name="order_sync.sync_order_to_sap")
def sync_order_to_sap(order_sync_id):
    order = db.claim_order(order_sync_id)
    if order is None:
        return {"status": "skipped", "order_sync_id": order_sync_id}
    sap = None
    odoo = None
    post_started = False
    result = None
    stage = "validate_config"
    try:
        if order["odoo_db"] != get_config()["odoo_order_sync"]["db"]:
            raise ValueError("Order Odoo database differs from current configuration")
        stage = "sap_init"
        sap = SapClient()
        stage = "sap.login"
        sap.login()
        stage = "sap.find_order"
        result = sap.find_order(order["sap_external_key"])
        if result is None:
            stage = "odoo_init"
            odoo = OdooClient()
            stage = "odoo.build_sap_payload"
            payload = odoo.build_sap_payload(order)
            post_started = True
            stage = "sap.create_order"
            result = sap.create_order(payload)
    except Exception as exc:
        status = failure_status(order, exc, post_started)
        error = f"stage={stage}; {type(exc).__name__}: {exc}"
        db.finish_order(order, status, error=error)
        logger.warning("Order %s moved to %s: %s", order_sync_id, status, error, exc_info=True)
        return {"status": status, "order_sync_id": order_sync_id}
    finally:
        if odoo is not None:
            odoo.close()
        if sap is not None:
            sap.close()
    # Failure here must not be treated as a failed SAP POST or cause another POST.
    db.finish_order(order, "done", sap_order=result)
    return {"status": "done", "order_sync_id": order_sync_id}
