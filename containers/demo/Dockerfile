# Demo client: OKP retrieve + Llama Stack Responses API (UBI 9 + Python 3.9)
# Build from repo root: podman build -f containers/demo/Dockerfile -t rhokp-demo .
# Run: podman run --rm -e RHOKP_BASE_URL=http://okp:8080 -e LLAMA_STACK_BASE=https://... --network rhokp-net rhokp-demo "Your question"

FROM registry.redhat.io/ubi9/python-39:latest

USER 0
# Demo script uses stdlib only (urllib); no pip deps required

WORKDIR /app
COPY src/       /app/src/
COPY demo/      /app/demo/

ENV PYTHONPATH=/app/src
ENTRYPOINT ["python3", "demo/ask_okp.py"]
CMD []
