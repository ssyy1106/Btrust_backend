"""Exactly two periodic tasks; no recovery/expired-lease scanner."""
from order_sync.config import get_config


def get_beat_schedule():
    settings = get_config()["celery_order_sync"]
    for name in ("poll_interval_seconds", "publish_interval_seconds", "broker_timeout_seconds",
                 "odoo_page_size", "publish_batch_size", "max_attempts"):
        if settings.getfloat(name) <= 0:
            raise ValueError(f"[celery_order_sync] {name} must be positive")
    return {
        "poll-odoo-orders": {
            "task": "order_sync.poll_odoo_orders",
            "schedule": settings.getfloat("poll_interval_seconds"),
        },
        "publish-order-outbox": {
            "task": "order_sync.publish_outbox",
            "schedule": settings.getfloat("publish_interval_seconds"),
        },
    }
