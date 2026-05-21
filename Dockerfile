FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml relay_mcp.py ./

RUN pip install --no-cache-dir . \
    && adduser --system --uid 1000 --no-create-home relay

USER relay

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',8888)); s.close()" || exit 1

CMD ["relay-mcp", "--transport", "http", "--port", "8888"]
