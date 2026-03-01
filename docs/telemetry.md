# Telemetry

## RHOKP telemetry and rhokp-agent

RHOKP collects and transmits telemetry data including Solr queries and RAG queries. This telemetry is opt-out by default and auto-disables in disconnected environments where the telemetry endpoint is unreachable.

When rhokp-agent queries RHOKP's Solr API, those queries are visible to RHOKP's telemetry system. This section describes how rhokp-agent identifies itself and what data flows are involved.

## User-Agent identification

rhokp-agent includes a `User-Agent` header in all HTTP requests to RHOKP:

```
User-Agent: rhokp-agent/<version>
```

This allows the RHOKP product team to distinguish agent-generated queries from human UI queries in telemetry data. The header is always sent and cannot be disabled.

## What data rhokp-agent sends to RHOKP

rhokp-agent sends only Solr search requests to RHOKP. Each request contains:

| Parameter | Example | Purpose |
|-----------|---------|---------|
| `q` | `install OpenShift` | The search query (sanitized) |
| `rows` | `5` | Number of results requested |
| `wt` | `json` | Response format |
| `fq` | `product:"OpenShift Container Platform"` | Optional filter queries |
| `User-Agent` | `rhokp-agent/0.5.0` | Client identification |

No user credentials, session tokens, access keys, or personally identifiable information are sent by rhokp-agent. The ACCESS_KEY used to start the RHOKP container is not part of the Solr query path.

## What data rhokp-agent does NOT send

- No data is sent to any external service (PyPI, GitHub, Red Hat, etc.)
- No usage analytics or crash reports are collected by rhokp-agent
- No LLM prompts, responses, or conversation history leave the local environment
- OpenTelemetry tracing (if enabled) stays within your configured OTel collector

## OpenTelemetry integration

rhokp-agent optionally supports OpenTelemetry tracing (`pip install rhokp[observability]`). When enabled, spans are created for each `retrieve()` / `aretrieve()` call with attributes:

| Attribute | Description |
|-----------|-------------|
| `okp.query` | The search query |
| `okp.rows` | Requested rows |
| `okp.base_url` | RHOKP base URL |
| `okp.num_found` | Total Solr hits |
| `okp.docs_returned` | Documents returned |
| `okp.elapsed_ms` | Round-trip time |

Traces are exported to your configured OpenTelemetry collector. No traces are sent to Red Hat or any external party.
