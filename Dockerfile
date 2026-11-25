# JMK Traders: one container = website + server. Built and run by Render.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FRONTEND_DIR=/app/frontend
WORKDIR /app/backend
COPY backend/requirements-prod.txt ./
RUN pip install -r requirements-prod.txt
COPY backend/ ./
COPY frontend/ /app/frontend/
EXPOSE 10000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
