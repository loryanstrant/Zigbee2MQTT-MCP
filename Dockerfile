FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080

WORKDIR /app

# Install dependencies first (better layer caching), then the package.
COPY pyproject.toml README.md ./
COPY zigbee2mqtt_mcp ./zigbee2mqtt_mcp
RUN pip install --no-cache-dir .

# Run as a non-root user.
RUN useradd --system --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

ENTRYPOINT ["python", "-m", "zigbee2mqtt_mcp"]
