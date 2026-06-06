FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DINGTALK_GATEWAY_ENV=production \
    DINGTALK_GATEWAY_HOST=0.0.0.0 \
    DINGTALK_GATEWAY_PORT=8787 \
    DINGTALK_GATEWAY_REQUIRE_AUTH=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src
RUN pip install --no-cache-dir . && mkdir -p logs reports

EXPOSE 8787
CMD ["dingtalk-codex-gateway"]
