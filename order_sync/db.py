"""Short, synchronous transactions for Celery; no FastAPI lifespan dependency."""
from contextlib import contextmanager
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

from .config import get_config


@contextmanager
def transaction():
    settings = get_config()["postgresqlstorestock"]
    conn = psycopg2.connect(
        host=settings["host"], port=settings.getint("port"),
        user=settings["username"], password=settings["password"],
        dbname=settings["database"], connect_timeout=10,
        options="-c search_path=public -c statement_timeout=30000 -c lock_timeout=10000",
    )
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
    finally:
        conn.close()


def insert_order(odoo_db, order, max_attempts):
    # Only a newly inserted order gets an event, in the same SQL transaction.
    with transaction() as cur:
        cur.execute("""
            WITH new_order AS (
                INSERT INTO order_sync
                    (odoo_db, odoo_order_id, odoo_order_name, sap_external_key, max_attempts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (odoo_db, odoo_order_id) DO NOTHING
                RETURNING id
            )
            INSERT INTO order_outbox (order_sync_id)
            SELECT id FROM new_order RETURNING id
        """, (odoo_db, order["id"], order["name"],
              f"ODOO-{odoo_db}-{order['id']}", max_attempts))
        return cur.fetchone() is not None


def enqueue_due_retries():
    # Normal business retries only; never reclaim processing/publishing rows.
    with transaction() as cur:
        # The existing database has no uq_outbox_active index. Serialize retry
        # event creation across publishers without changing the user's schema.
        cur.execute("SELECT pg_try_advisory_xact_lock(741203, 1) AS acquired")
        if not cur.fetchone()["acquired"]:
            return
        cur.execute("""
            INSERT INTO order_outbox (order_sync_id)
            SELECT s.id FROM order_sync s
            WHERE s.status = 'retry' AND s.next_retry_at <= NOW()
              AND s.attempt_count < s.max_attempts
              AND NOT EXISTS (
                SELECT 1 FROM order_outbox o WHERE o.order_sync_id = s.id
                  AND o.event_type = 'sync_to_sap'
                  AND o.status IN ('pending', 'publishing')
              )
            ON CONFLICT DO NOTHING
        """)


def claim_outbox():
    token = str(uuid4())
    with transaction() as cur:
        cur.execute("""
            WITH candidate AS (
                SELECT id FROM order_outbox
                WHERE status = 'pending' AND event_type = 'sync_to_sap'
                  AND next_attempt_at <= NOW()
                ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE order_outbox o
            SET status = 'publishing', lock_token = %s,
                publish_attempts = publish_attempts + 1
            FROM candidate c WHERE o.id = c.id RETURNING o.*
        """, (token,))
        return cur.fetchone()


def finish_publish(event, error=None):
    with transaction() as cur:
        if error is None:
            cur.execute("""
                UPDATE order_outbox SET status = 'published', published_at = NOW(),
                    lock_token = NULL, locked_until = NULL, last_error = NULL
                WHERE id = %s AND status = 'publishing' AND lock_token = %s
            """, (event["id"], event["lock_token"]))
        else:
            delay = min(300, 10 * 2 ** min(event["publish_attempts"] - 1, 5))
            cur.execute("""
                UPDATE order_outbox SET status = 'pending', lock_token = NULL,
                    locked_until = NULL, last_error = %s,
                    next_attempt_at = NOW() + %s * INTERVAL '1 second'
                WHERE id = %s AND status = 'publishing' AND lock_token = %s
            """, (error[:4000], delay, event["id"], event["lock_token"]))


def claim_order(order_sync_id):
    with transaction() as cur:
        cur.execute("""
            UPDATE order_sync SET status = 'processing', lock_token = %s,
                attempt_count = attempt_count + 1, updated_at = NOW()
            WHERE id = %s AND attempt_count < max_attempts
              AND (status = 'pending' OR
                   (status = 'retry' AND next_retry_at <= NOW()))
            RETURNING *
        """, (str(uuid4()), order_sync_id))
        return cur.fetchone()


def finish_order(order, status, error=None, sap_order=None):
    delay = min(300, 30 * 2 ** min(order["attempt_count"] - 1, 4))
    with transaction() as cur:
        cur.execute("""
            UPDATE order_sync SET status = %s, last_error = %s,
                sap_doc_entry = %s, sap_doc_num = %s,
                next_retry_at = CASE WHEN %s = 'retry'
                    THEN NOW() + %s * INTERVAL '1 second' ELSE NULL END,
                lock_token = NULL, locked_until = NULL, updated_at = NOW()
            WHERE id = %s AND status = 'processing' AND lock_token = %s
        """, (status, error[:4000] if error else None,
              sap_order.get("DocEntry") if sap_order else None,
              sap_order.get("DocNum") if sap_order else None,
              status, delay, order["id"], order["lock_token"]))
        if cur.rowcount != 1:
            raise RuntimeError(f"Order {order['id']} no longer owned by this worker")
