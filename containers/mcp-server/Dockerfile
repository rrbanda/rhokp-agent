# MCP server for OKP search (UBI 9 + Python 3.9)
# Build from repo root: podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .

FROM registry.redhat.io/ubi9/python-39:latest

USER 0
RUN pip install --no-cache-dir 'fastapi>=0.100.0' 'uvicorn[standard]>=0.22.0'

WORKDIR /app
COPY src/           /app/src/
COPY mcp_server/    /app/mcp_server/

ENV PYTHONPATH=/app/src
EXPOSE 8010

USER 1001
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8010"]
