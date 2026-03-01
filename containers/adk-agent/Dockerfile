# ADK agent + web UI for RHOKP
# Build from repo root: podman build -f containers/adk-agent/Dockerfile -t rhokp-adk .

FROM docker.io/library/python:3.12-slim

RUN groupadd -r rhokp && useradd -r -g rhokp -d /app rhokp

WORKDIR /app
COPY pyproject.toml /app/
COPY src/           /app/src/
COPY agent/         /app/agent/

RUN pip install --no-cache-dir /app[adk]

EXPOSE 8000

USER rhokp
CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8000"]
