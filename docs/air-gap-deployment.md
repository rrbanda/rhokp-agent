# Air-Gap Deployment Guide

RHOKP's primary audience is air-gapped, disconnected, and security-sensitive environments. This guide covers deploying rhokp-agent alongside RHOKP in environments with no internet access.

## Architecture in disconnected environments

```
┌─────────────────────────────────────────────────────────┐
│  Air-gapped network                                     │
│                                                         │
│  ┌──────────────┐    ┌─────────────────┐                │
│  │ RHOKP        │◄───│ rhokp-agent     │                │
│  │ (container)  │    │ (MCP server or  │                │
│  │ :8080/:8443  │    │  Python library) │                │
│  └──────────────┘    └────────┬────────┘                │
│                               │                         │
│                      ┌────────▼────────┐                │
│                      │ Local LLM       │                │
│                      │ (Llama Stack,   │                │
│                      │  Ollama, etc.)  │                │
│                      └─────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

All three components run on the local network with no external dependencies at runtime.

## Prerequisites

Before entering the air-gapped environment, prepare these artifacts on a connected machine:

### 1. RHOKP container image

```bash
# On a connected machine with Red Hat registry access:
podman pull registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
podman save -o rhokp-image.tar \
    registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
```

### 2. rhokp-agent container image (MCP server)

```bash
# Option A: Pull pre-built image
podman pull quay.io/rbrhssa/rhokp-mcp:latest
podman save -o rhokp-mcp.tar quay.io/rbrhssa/rhokp-mcp:latest

# Option B: Build locally from source
git clone https://github.com/rrbanda/rhokp-agent.git
cd rhokp-agent
podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp:latest .
podman save -o rhokp-mcp.tar rhokp-mcp:latest
```

### 3. rhokp-agent Python wheel (for library use)

```bash
cd rhokp-agent
pip wheel --no-deps -w dist/ .
pip wheel --no-deps -w dist/ httpx
pip wheel --no-deps -w dist/ fastmcp  # if using MCP
# The dist/ directory now contains all wheels for offline install
```

### 4. Local LLM

Deploy a local LLM backend that can run without internet:
- [Llama Stack](https://github.com/red-hat-data-services/llama-stack) with a local model
- [Ollama](https://ollama.ai) with a pre-downloaded model
- Any OpenAI-compatible API running locally

## Deployment in the air-gapped environment

### Transfer artifacts

Transfer the saved container images and wheels into the air-gapped environment via approved media (USB, optical disc, data diode, etc.).

### Load container images

```bash
podman load -i rhokp-image.tar
podman load -i rhokp-mcp.tar
```

### Start RHOKP

```bash
podman run --rm -d --name okp \
    -p 8080:8080 -p 8443:8443 --memory=4g \
    -e ACCESS_KEY=<your_access_key> \
    -e SOLR_MEM=1g \
    registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
```

### Option A: Run MCP server as a container

```bash
podman run -d --name rhokp-mcp \
    -p 8010:8010 \
    -e RHOKP_BASE_URL=http://host.containers.internal:8080 \
    rhokp-mcp:latest
```

### Option B: Install Python library from wheels

```bash
pip install --no-index --find-links=dist/ rhokp
# or with MCP support:
pip install --no-index --find-links=dist/ "rhokp[mcp]"
```

Then use the library directly:

```python
from rhokp import retrieve
result = retrieve("install OpenShift", base_url="http://okp-host:8080")
print(result.context)
```

## Runtime network requirements

rhokp-agent makes **zero external network calls** at runtime. All communication is between local services:

| Source | Destination | Protocol | Port | Purpose |
|--------|------------|----------|------|---------|
| rhokp-agent | RHOKP | HTTP | 8080 | Solr search queries |
| rhokp-agent | RHOKP | HTTPS | 8443 | Solr search queries (TLS) |
| ADK agent | LLM backend | HTTP(S) | varies | LLM inference |

The `fastmcp` library used by the MCP server operates entirely over local HTTP -- no external service discovery, no telemetry callbacks, no license checks.

## Updating content

RHOKP content is updated by pulling a new container image. In air-gapped environments:

1. On a connected machine, pull the latest RHOKP image
2. Save it with `podman save`
3. Transfer to the air-gapped environment
4. Load and restart: `podman load -i rhokp-new.tar && podman restart okp`

rhokp-agent itself does not need updating when RHOKP content changes -- it queries the Solr API dynamically.

## TLS considerations

For environments requiring TLS between rhokp-agent and RHOKP:

```bash
# Point to RHOKP's HTTPS port and provide a CA bundle
export RHOKP_BASE_URL=https://okp-host:8443
export RHOKP_VERIFY_SSL=/path/to/ca-bundle.crt
```

Or disable verification for self-signed certificates (not recommended for production):

```bash
export RHOKP_VERIFY_SSL=false
```

## Resource requirements

| Component | Memory | CPU | Disk |
|-----------|--------|-----|------|
| RHOKP | 4 GB (1 GB for Solr) | 2 cores | ~15 GB (image + index) |
| rhokp-agent (MCP server) | 128 MB | 0.5 cores | 200 MB (image) |
| Local LLM | 8-32 GB (model dependent) | 4+ cores or GPU | varies |

All three components can run on a single laptop or small server.
