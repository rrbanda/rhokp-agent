# RHOKP Deployment

This directory contains deployment manifests for running the RHOKP stack
(Offline Knowledge Portal + MCP server + ADK agent web UI).

Two deployment paths are supported:

| Path          | Tool                    | Secret handling              |
| ------------- | ----------------------- | ---------------------------- |
| **Local**     | `podman-compose`        | `.env` file or shell exports |
| **OpenShift** | `oc apply -k` (Kustomize) | Kubernetes `Secret` object |

---

## Local development (Podman Compose)

### 1. Create a `.env` file

Copy the example and fill in your values:

```bash
cp .env.example .env
# edit .env — set ACCESS_KEY and LLAMA_STACK_BASE_URL
```

> **Never commit `.env`** — it is already in `.gitignore`.

### 2. Start the stack

```bash
podman-compose up          # all three services
podman-compose up rhokp mcp-server  # without the agent web UI
```

### 3. Verify

| Service     | URL                                  |
| ----------- | ------------------------------------ |
| OKP (Solr)  | http://localhost:8080                |
| MCP server  | http://localhost:8010/mcp            |
| ADK web UI  | http://localhost:8000                |

---

## OpenShift / Kubernetes

All manifests live in `deploy/openshift/` and are wired together via Kustomize.

### Prerequisites

- `oc` CLI logged into the target cluster
- Access to pull the container images:
  - `registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest`
  - `quay.io/rbrhssa/rhokp-mcp:latest`
  - `quay.io/rbrhssa/rhokp-adk:latest`

### 1. Create the secret

```bash
oc create secret generic rhokp-secrets \
  --from-literal=ACCESS_KEY=<your_okp_access_key> \
  --from-literal=LLAMA_STACK_BASE_URL=https://<your_llama_stack_endpoint>
```

To update an existing secret:

```bash
oc patch secret rhokp-secrets -p \
  '{"stringData":{"ACCESS_KEY":"new-key","LLAMA_STACK_BASE_URL":"https://new-endpoint"}}'
```

### 2. Deploy with Kustomize

```bash
oc apply -k deploy/openshift/
```

This creates:

| Resource     | Kind         | Description                     |
| ------------ | ------------ | ------------------------------- |
| `rhokp`      | Deployment   | OKP Solr + httpd on port 8080  |
| `rhokp`      | Service      | ClusterIP for OKP              |
| `mcp-server` | Deployment   | MCP server on port 8010        |
| `mcp-server` | Service      | ClusterIP for MCP              |
| `adk-web`    | Deployment   | ADK agent web UI on port 8000  |
| `adk-web`    | Service      | ClusterIP for ADK              |
| `adk-web`    | Route        | Edge-terminated TLS route      |

### 3. Verify

```bash
oc get pods -l app.kubernetes.io/part-of=rhokp
oc get route adk-web -o jsonpath='{.spec.host}'
```

The Route URL is the public entry point for the ADK web UI.

### 4. Architecture

```
┌──────────────────────────────────────────────────────┐
│  OpenShift namespace                                 │
│                                                      │
│  Secret: rhokp-secrets                               │
│    ACCESS_KEY, LLAMA_STACK_BASE_URL                  │
│          │ envFrom                                   │
│          ▼                                           │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────┐ │
│  │   rhokp     │◄───│  mcp-server  │◄───│ adk-web │ │
│  │  :8080      │    │  :8010       │    │ :8000   │ │
│  │  (Solr)     │    │  (MCP/SSE)   │    │ (ADK)   │ │
│  └─────────────┘    └──────────────┘    └────┬────┘ │
│                                              │      │
│                                         Route│(TLS) │
└──────────────────────────────────────────────┼──────┘
                                               ▼
                                          End users
```

---

## Secrets reference

| Key                    | Required by      | Description                              |
| ---------------------- | ---------------- | ---------------------------------------- |
| `ACCESS_KEY`           | `rhokp`          | Decryption key for OKP encrypted content |
| `LLAMA_STACK_BASE_URL` | `adk-web`        | Llama Stack inference endpoint URL       |

Both keys are stored in a single `rhokp-secrets` Secret and injected into
the relevant pods via `envFrom`. Containers ignore keys they do not use.
