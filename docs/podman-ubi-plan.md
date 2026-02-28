# Plan: Running rhokp-agent components as Podman containers (UBI-based)

This document describes how to run the **MCP server** and the **demo (agent) client** as separate containers using Podman, with Red Hat Universal Base Image (UBI) as the base. It is intended to be done step-by-step; no rush.

---

## 1. Overview

### Components and containers

| Component | Role | Container | Base image |
|-----------|------|-----------|------------|
| **OKP** | Red Hat Offline Knowledge Portal (search backend) | Existing image; you already run it | `registry.redhat.io/offline-knowledge-portal/rhokp-rhel9` |
| **MCP server** | HTTP service exposing `search_red_hat_docs` (MCP JSON-RPC) | New: `rhokp-mcp` | UBI 9 + Python 3.9 |
| **Demo client** | One-off or script runner: OKP retrieve + Llama Stack Responses API | New: `rhokp-demo` | UBI 9 + Python 3.9 |

- **OKP** and **MCP server** are long-running services.
- **Demo client** is typically run as a one-off container (run with a question, print answer, exit). Optionally it can be wrapped in a small HTTP service later; this plan focuses on the one-off script runner.

### Communication

- **MCP server** → **OKP**: HTTP (e.g. `http://okp:8080` when on a shared Podman network).
- **Demo client** → **OKP**: HTTP (same network).
- **Demo client** → **Llama Stack**: HTTPS (external URL; set via env).
- **Llama Stack** (or other MCP client) → **MCP server**: HTTP (when registering the tool; MCP server must be reachable at a URL the client can use).

### Design principles

- **No secrets in images**: Pass URLs, keys, and tokens via environment or Podman secrets at runtime.
- **UBI-based**: Use official Red Hat UBI 9 Python images for consistency and support.
- **Minimal images**: Only install runtime dependencies; build in a builder stage if needed.
- **Reproducible**: Dockerfiles and scripts in the repo; document exact `podman` commands.

---

## 2. Prerequisites

- **Podman** installed (rootless or root).
- **Red Hat registry access** (for UBI and OKP images): e.g. `podman login registry.redhat.io` if required.
- **Repository** `rhokp-agent` cloned (e.g. `~/code/rhokp-agent`). Build context will be the repo root.
- **OKP** run separately (this plan can assume OKP is already running or include it in the “run order” section).

---

## 3. Base image choice

- **UBI 9 Python**: Use `registry.redhat.io/ubi9/python-39` (or the current Python 3.9 image from [Red Hat Ecosystem Catalog](https://catalog.redhat.com/software/containers/ubi9/python-39)).
- If that exact tag is not available, use `registry.redhat.io/ubi9/python-311` or the minimal `ubi9/minimal` and install Python via `microdnf`/`dnf`; the plan below assumes a UBI 9 image that provides `python3` and `pip` (or `pip3`).

Check locally:

```bash
podman pull registry.redhat.io/ubi9/python-39
```

---

## 4. Container 1: MCP server (`rhokp-mcp`)

### 4.1 Purpose

- Run the FastAPI app in `mcp_server/server.py`.
- Expose port 8010 (or configurable).
- Need: `src/rhokp/` and `mcp_server/` in the image; install deps from `mcp_server/requirements.txt`.

### 4.2 Dockerfile location and layout

- **Path**: `containers/mcp-server/Dockerfile` (or `mcp_server/Dockerfile`; plan uses `containers/mcp-server/` to keep container build context separate from app code).
- **Build context**: Repository root (so both `src/` and `mcp_server/` are available).

Suggested layout:

```
rhokp-agent/
  containers/
    mcp-server/
      Dockerfile
    demo/
      Dockerfile
```

### 4.3 Dockerfile (MCP server) – outline

- **FROM** `registry.redhat.io/ubi9/python-39` (or equivalent).
- **WORKDIR** `/app`.
- Copy `src/rhokp/` and `mcp_server/` (and `mcp_server/requirements.txt`).
- **RUN** install dependencies (e.g. `pip install --no-cache-dir -r mcp_server/requirements.txt`); do **not** install the app in editable mode if you copied only the needed subdirs (the app imports `rhokp` from `src`, so copy `src` into `/app/src` and set `PYTHONPATH=/app/src` or install `rhokp` from the repo root if you copy the whole repo).
- **ENV** `PYTHONPATH=/app/src` (so `from rhokp.retrieve import retrieve` works).
- **EXPOSE** 8010.
- **CMD** run uvicorn: e.g. `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8010` (if run from `/app` and repo root was copied to `/app`) **or** run the app as a module so the path is clear.

Simplest approach: **copy full repo** into `/app`, then:

```dockerfile
WORKDIR /app
COPY src/   /app/src/
COPY mcp_server/ /app/mcp_server/
RUN pip install --no-cache-dir -r mcp_server/requirements.txt
ENV PYTHONPATH=/app/src
EXPOSE 8010
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8010"]
```

But `uvicorn mcp_server.server:app` expects to be run from `/app` (repo root). So build context = repo root, `COPY . /app` (or copy only `src/`, `mcp_server/`, and `pyproject.toml` if you install the package). The plan should spell this out so the Dockerfile is unambiguous.

### 4.4 Environment variables (runtime, no secrets in image)

- `RHOKP_BASE_URL`: OKP base URL. When OKP runs as a container on the same Podman network, use the OKP container name (e.g. `http://okp:8080`).
- `RHOKP_RAG_ROWS`: Optional; default 5.

### 4.5 Build and run (Podman)

- **Build**: from repo root,  
  `podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .`
- **Run**:  
  `podman run -d --name rhokp-mcp -p 8010:8010 -e RHOKP_BASE_URL=http://<okp-host>:8080 --network <shared-network> rhokp-mcp`  
  Replace `<okp-host>` with the OKP container name if on the same network, or host/IP if not.

### 4.6 Health check

- **GET** `http://localhost:8010/health` → 200 and `{"status":"ok","service":"okp-mcp"}`.
- **POST** `http://localhost:8010/mcp` with JSON-RPC `tools/list` → list including `search_red_hat_docs`.

---

## 5. Container 2: Demo / agent client (`rhokp-demo`)

### 5.1 Purpose

- Run `demo/ask_okp.py` with a question (and env for OKP and Llama Stack).
- Either:
  - **One-off**: `podman run --rm rhokp-demo "How do I install OpenShift?"` → container runs script, prints answer, exits; or
  - **Interactive**: `podman run -it --rm rhokp-demo` then type a question (if we add a wrapper script).

This plan assumes **one-off** with the question passed as the container command or args.

### 5.2 Dockerfile (demo) – outline

- **FROM** same UBI 9 Python base.
- **WORKDIR** `/app`.
- Copy `src/rhokp/`, `demo/ask_okp.py` (and any `demo/` deps; currently the demo uses only stdlib + `rhokp`).
- No extra pip deps for the demo (retrieve is stdlib; Llama Stack call is `urllib`).
- **ENV** `PYTHONPATH=/app/src`.
- **ENTRYPOINT** `["python3", "demo/ask_okp.py"]` and **CMD** `[]` so you can run:  
  `podman run --rm -e ... rhokp-demo "Your question here"`.

### 5.3 Environment variables (runtime)

- `RHOKP_BASE_URL`: OKP URL (e.g. `http://okp:8080` on shared network).
- `LLAMA_STACK_BASE`: Llama Stack base URL (required for the script).
- `MODEL`: Optional; default in script.

No secrets in the image; if Llama Stack requires a token, pass it via `-e` or Podman secret and have the script read it (script would need a small change to support an optional auth header).

### 5.4 Build and run

- **Build**: `podman build -f containers/demo/Dockerfile -t rhokp-demo .`
- **Run (one-off)**:  
  `podman run --rm -e RHOKP_BASE_URL=http://okp:8080 -e LLAMA_STACK_BASE=https://your-llama-stack --network <shared-network> rhokp-demo "How do I install OpenShift on bare metal?"`

---

## 6. OKP container (reference)

- You already run OKP (e.g. Podman with `rhokp-rhel9`). For a clean setup, run it on the **same Podman network** as the MCP server and demo client so they can use the container name as hostname.
- Example (unchanged from your existing flow):  
  `podman run -d --name okp -p 8080:8080 -p 8443:8443 --memory=4g -e ACCESS_KEY=<...> -e SOLR_MEM=1g --network rhokp-net registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest`
- **Do not** put `ACCESS_KEY` in any Dockerfile or committed file; pass it at run time.

---

## 7. Networking

### 7.1 Create a shared network

```bash
podman network create rhokp-net
```

### 7.2 Attach all service containers to it

- OKP: `--network rhokp-net --name okp`
- MCP server: `--network rhokp-net --name rhokp-mcp`
- Demo: `--network rhokp-net` (for one-off runs)

Then:

- **MCP server** and **demo** reach OKP at `http://okp:8080`.
- Host reaches MCP server at `localhost:8010` if you published the port (`-p 8010:8010`).
- Llama Stack is outside the host; demo container needs network access to the internet (or your cluster) to call `LLAMA_STACK_BASE`.

### 7.3 DNS

- Podman’s built-in DNS resolves container names on the same network. No extra DNS config needed.

---

## 8. Secrets and credentials

- **OKP access key**: Pass only at `podman run` for the OKP container (`-e ACCESS_KEY=...` or `--secret`). Not in any Dockerfile or in the rhokp-agent repo.
- **Llama Stack**: If the API requires a token, pass it via `-e LLAMA_STACK_TOKEN=...` or a Podman secret and extend the demo script to send the header; do not bake into the image.
- **.env files**: Do not copy `.env` into the image. Use `--env-file` at runtime if desired, and keep `.env` out of the build context or in `.dockerignore`.

### 8.1 .dockerignore

- Add a **.dockerignore** at repo root so that `.env`, `.git`, `__pycache__`, `.venv`, and other unneeded files are not sent to the build context.

---

## 9. Build and run order

1. **Create network**: `podman network create rhokp-net`
2. **Start OKP** (if not already running):  
   `podman run -d --name okp -p 8080:8080 -p 8443:8443 --memory=4g -e ACCESS_KEY=... -e SOLR_MEM=1g --network rhokp-net registry.redhat.io/...`
3. **Build MCP server image**: from repo root, `podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .`
4. **Run MCP server**:  
   `podman run -d --name rhokp-mcp -p 8010:8010 -e RHOKP_BASE_URL=http://okp:8080 --network rhokp-net rhokp-mcp`
5. **Verify MCP**: `curl -s http://localhost:8010/health` and POST `/mcp` with `tools/list`
6. **Build demo image**: `podman build -f containers/demo/Dockerfile -t rhokp-demo .`
7. **Run demo (one-off)**:  
   `podman run --rm -e RHOKP_BASE_URL=http://okp:8080 -e LLAMA_STACK_BASE=https://... --network rhokp-net rhokp-demo "How do I install OpenShift?"`

---

## 10. Optional: Pod or Compose

- **Podman pod**: You can create a pod and run OKP + MCP server in the same pod so they share localhost; then only the pod’s port mapping is needed. The plan above uses a shared network instead so that OKP can stay a pre-existing container.
- **Compose**: If you prefer a single file, add a `compose.yaml` (Podman Compose or Docker Compose) that defines the network, OKP (or use external), MCP server, and optionally the demo as a one-off service. Document in a later section or a separate file so the plan stays focused on “how to run as different containers with Podman and UBI.”

---

## 11. File checklist (to implement)

After the plan is agreed, the repo would add:

| File | Purpose |
|------|--------|
| `.dockerignore` | Exclude .env, .git, __pycache__, .venv, etc. from build context |
| `containers/mcp-server/Dockerfile` | UBI 9 + Python; copy src + mcp_server; run uvicorn |
| `containers/demo/Dockerfile` | UBI 9 + Python; copy src + demo; ENTRYPOINT demo script |
| `docs/podman-ubi-plan.md` | This plan |
| Optional: `containers/README.md` | Short pointer to this plan and the exact podman commands |
| Optional: `compose.yaml` | For those who prefer compose |

---

## 12. Testing the containers

- **MCP server**: After run, from host: `curl -s http://localhost:8010/health` and a JSON-RPC `tools/list` to `http://localhost:8010/mcp`. From another container on `rhokp-net`: `curl -s http://rhokp-mcp:8010/health`.
- **Demo**: Run the one-off command with a real question and confirm stdout shows the model’s answer (or a clear error if Llama Stack is unreachable or env is wrong).
- **No secrets**: Grep the built images’ layers for sensitive strings if needed (e.g. `podman history rhokp-mcp` and inspect envs); nothing secret should be in the Dockerfile or in copied files.

---

## 13. Summary

- **Two new containers**: MCP server (long-running), Demo (one-off script runner).
- **Both UBI 9 + Python**; no secrets in images; config via env and optional secrets at runtime.
- **Shared Podman network** so MCP and demo can reach OKP by name; OKP and MCP server can be started first, then demo run on demand.
- **Next step**: Add `.dockerignore`, then `containers/mcp-server/Dockerfile` and `containers/demo/Dockerfile`, then test build and run following section 9.
