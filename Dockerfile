FROM python:3.12

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    unixodbc \
    ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    -i https://pypi.org/simple

COPY ./ /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
