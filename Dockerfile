FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY copilot ./copilot
COPY personas ./personas

RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn copilot.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
