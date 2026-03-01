# MCP server for OKP search
# Build from repo root: podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .

FROM docker.io/library/python:3.12-slim

RUN groupadd -r rhokp && useradd -r -g rhokp -d /app rhokp

WORKDIR /app
COPY pyproject.toml /app/
COPY src/           /app/src/

RUN pip install --no-cache-dir /app[mcp]

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8010/mcp', timeout=5)" || exit 1

USER rhokp
CMD ["rhokp-mcp"]
