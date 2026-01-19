FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 系统依赖（psycopg / cryptography 等常用依赖会用到）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host pypi.python.org \
    -r /app/requirements.txt

COPY . /app

# 默认启动 Celery worker（compose 里也可以覆盖 command）
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "-l", "INFO", "--concurrency=4", "-Q", "default"]
