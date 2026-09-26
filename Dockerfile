FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SMS_GATEWAY_HOST=0.0.0.0 \
    SMS_GATEWAY_PORT=8787 \
    SMS_GATEWAY_DB=/data/sms_gateway.db \
    SMS_GATEWAY_SERIAL_PORT=auto

WORKDIR /app
RUN groupadd --gid 10001 gateway \
    && useradd --uid 10001 --gid gateway --groups dialout --create-home gateway \
    && mkdir -p /data \
    && chown gateway:gateway /data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY sms_gateway/ ./sms_gateway/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist/

USER gateway
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=3)); assert d['ok']" || exit 1
CMD ["python", "-m", "sms_gateway"]
