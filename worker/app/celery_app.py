import os
import json
import gzip
from celery import Celery
from pathlib import Path
from datetime import datetime

# =========================
# 1. 环境变量
# =========================

BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "amqp://app:apppass@localhost:5672//",
)

RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    "rpc://",
)

# 用于演示：本地 payload 存储目录（你以后可换 MinIO）
PAYLOAD_DIR = Path(os.getenv("PAYLOAD_DIR", "/data/jobs"))
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# 2. 创建 Celery 实例（核心）
# =========================

celery_app = Celery(
    "worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 可靠性
    task_acks_late=True,              # 执行完才 ack
    worker_prefetch_multiplier=1,     # 每个 worker 一次只拿 1 个任务

    # 时间相关
    enable_utc=True,
    timezone="UTC",

    # 日志
    worker_hijack_root_logger=False,
)

# =========================
# 3. 示例 Task（你可以照这个写业务）
# =========================

@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_kwargs={"max_retries": 3},
    name="process_job",   # 明确 task 名，方便 send_task
)
def process_job(self, job_id: str):
    """
    示例后台任务：
    - 读取 gzip JSON
    - 打印一些信息
    - 模拟处理
    """

    payload_file = PAYLOAD_DIR / f"{job_id}.json.gz"

    if not payload_file.exists():
        raise FileNotFoundError(f"Payload not found: {payload_file}")

    # 读取 gzip JSON
    with gzip.open(payload_file, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    # ===== 模拟处理逻辑 =====
    print("=" * 60)
    print(f"[{datetime.utcnow().isoformat()}] Processing job:", job_id)
    print("Payload keys:", list(payload.keys())[:10])
    print("=" * 60)

    # TODO: 这里换成你真实的逻辑
    # - 校验
    # - 入库
    # - 统计
    # - 写 jobs 表

    return {
        "job_id": job_id,
        "status": "success",
    }
