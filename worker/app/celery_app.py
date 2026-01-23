import os
import json
import asyncio
import uuid
from datetime import datetime

import asyncpg
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from celery import Celery

# =========================
# 1. Basic settings
# =========================

BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "amqp://app:apppass@localhost:5672//",
)

RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    "rpc://",
)

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minio")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minio123456")
S3_BUCKET = os.getenv("S3_BUCKET", "jobs")

DATABASE_URL = os.getenv("DATABASE_URL")

# =========================
# 2. Celery setup
# =========================

celery_app = Celery(
    "worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    enable_utc=True,
    timezone="UTC",
    worker_hijack_root_logger=False,
)


def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _ensure_bucket(client, bucket: str):
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchBucket"}:
            client.create_bucket(Bucket=bucket)
        else:
            raise


def _normalize_db_url(url: str) -> str:
    if not url:
        try:
            from helper import getStockConfig
        except Exception:
            raise RuntimeError("DATABASE_URL is not set and helper is unavailable")
        username, password, host, database, port = getStockConfig()
        return f"postgresql://{username}:{password}@{host}:{port}/{database}"
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


async def _fetch_payload(job_id: str, payload_key: str) -> dict:
    s3_client = _get_s3_client()
    await asyncio.to_thread(_ensure_bucket, s3_client, S3_BUCKET)
    response = await asyncio.to_thread(
        s3_client.get_object,
        Bucket=S3_BUCKET,
        Key=payload_key,
    )
    body = await asyncio.to_thread(response["Body"].read)
    return json.loads(body)


async def _process_stocktake(conn, payload: dict):
    session_id = payload.get("id")
    if not session_id:
        raise ValueError("payload.id is missing")
    if isinstance(session_id, str):
        session_id = uuid.UUID(session_id)

    stocktake = payload.get("stocktake") or []
    session_creator = stocktake[0].get("user_id") if stocktake else "system"
    timestamp = _parse_dt(payload.get("timestamp"))
    device_id = payload.get("deviceId")
    now = datetime.now()

    await conn.execute("DELETE FROM stocktake_item WHERE session_id=$1", session_id)
    await conn.execute("DELETE FROM stocktake_session WHERE id=$1", session_id)

    await conn.execute(
        """
        INSERT INTO stocktake_session
            (id, device_id, timestamp, creator_id, modifier_id, create_time, update_time)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7)
        """,
        session_id,
        device_id,
        timestamp,
        str(session_creator),
        str(session_creator),
        now,
        now,
    )

    for item in stocktake:
        raw_barcode = item.get("barcode") or ""
        barcode = raw_barcode.strip()
        if not barcode:
            raise ValueError("barcode is required")
        await conn.execute(
            """
            INSERT INTO stocktake_item
                (session_id, id, location, barcode, qty, time, creator_id, modifier_id, create_time, update_time)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            session_id,
            int(item.get("id")),
            item.get("location"),
            barcode,
            int(item.get("qty")),
            _parse_dt(item.get("time")),
            str(item.get("user_id")),
            str(item.get("user_id")),
            now,
            now,
        )


async def _run_job(job_id: str):
    db_url = _normalize_db_url(DATABASE_URL)
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            "UPDATE jobs SET status=$2, update_time=NOW() WHERE id=$1",
            job_id,
            "processing",
        )
        row = await conn.fetchrow("SELECT payload_key FROM jobs WHERE id=$1", job_id)
        if not row:
            raise RuntimeError(f"Job not found: {job_id}")
        payload_key = row["payload_key"]

        payload = await _fetch_payload(job_id, payload_key)

        async with conn.transaction():
            await _process_stocktake(conn, payload)

        await conn.execute(
            "UPDATE jobs SET status=$2, update_time=NOW() WHERE id=$1",
            job_id,
            "completed",
        )
    except Exception:
        await conn.execute(
            "UPDATE jobs SET status=$2, update_time=NOW() WHERE id=$1",
            job_id,
            "failed",
        )
        raise
    finally:
        await conn.close()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_kwargs={"max_retries": 3},
    name="process_job",
)
def process_job(self, job_id: str):
    asyncio.run(_run_job(job_id))
    return {"job_id": job_id, "status": "success"}
