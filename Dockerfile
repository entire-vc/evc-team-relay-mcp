FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml relay_mcp.py ./

RUN pip install --no-cache-dir .

EXPOSE 8888

CMD ["relay-mcp", "--transport", "http", "--port", "8888"]
