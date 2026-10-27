"""Order synchronization worker (independent of the FastAPI process)."""
from celery import Celery
from kombu import Exchange, Queue

from order_sync.config import get_config
from celery_schedule import get_beat_schedule

settings = get_config()["celery_order_sync"]
queue = settings["queue"]
celery_app = Celery(
    "order_sync", broker=settings["broker_url"], include=["order_sync.tasks"]
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=settings.getfloat("broker_timeout_seconds"),
    broker_transport_options={
        "confirm_publish": True,
        "confirm_timeout": settings.getfloat("broker_timeout_seconds"),
    },
    task_default_queue=queue,
    task_default_exchange=queue,
    task_default_routing_key=queue,
    task_default_delivery_mode=2,
    task_create_missing_queues=False,
    task_queues=(Queue(queue, Exchange(queue, durable=True), routing_key=queue, durable=True),),
    timezone=settings["timezone"],
    enable_utc=True,
    worker_enable_remote_control=False,
    beat_schedule=get_beat_schedule(),
)
