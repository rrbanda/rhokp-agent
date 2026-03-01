# OKP Solr API Discovery

**Date:** 2026-02-28
**Source:** Live inspection of `registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest` (v1.3.18)
**Method:** Read `/opt/solr/server/solr/portal/conf/solrconfig.xml` and queried live endpoints

---

## 1. The `/select` handler is already production-tuned

The OKP Solr config uses `edismax` query parser with sophisticated field boosting, phrase matching, faceting, and highlighting -- all pre-configured. Our code should **leverage these defaults, not override them.**

### Default query configuration

```xml
<str name="defType">edismax</str>
<str name="qf">url_slug^20 title^15 main_content^10 product^8 syn_product^6
  documentation_version^5 all_content^2</str>
<str name="mm"><![CDATA[3<-1 5<70% 9<60%]]></str>
<str name="q.alt">*:*</str>
<str name="rows">10</str>

<!-- Phrase matching -->
<str name="pf">title^20 main_content^15</str>
<str name="pf2">title^12 main_content^6</str>
<str name="pf3">title^16 main_content^10</str>
```

**Implication:** We should NOT send `defType` -- edismax is already the default. The field boosting and phrase matching are already configured for Red Hat documentation. We should only send `q`, `rows`, and any filter queries (`fq`).

### Default highlighting

```xml
<str name="hl">on</str>
<str name="hl.method">original</str>
<str name="hl.fl">id title main_content product resourceName documentation_version</str>
<str name="hl.preserveMulti">true</str>
<str name="hl.snippets">2</str>
<str name="hl.encoder">html</str>
<str name="hl.simple.pre"><![CDATA[<b>]]></str>
<str name="hl.simple.post"><![CDATA[</b>]]></str>
<str name="hl.fragsize">150</str>
```

**Critical findings:**
- Highlight tags are `<b>` and `</b>` (not `<em>`)
- `hl.encoder=html` means the highlighted text contains HTML entities (`&#x27;`, `&quot;`, `&#x2F;`, etc.)
- `hl.fragsize=150` is the tuned default (our code overrides to 300)
- Highlighting covers 6 fields, not just 2

### Default faceting

```xml
<str name="facet">on</str>
<str name="facet.field">documentKind</str>
<str name="facet.field">portal_content_subtype</str>
<str name="facet.field">product</str>
<str name="facet.field">documentation_version</str>
<str name="facet.mincount">1</str>
```

**Implication:** Facets are ON by default. Every response includes product counts, document kind counts, and version counts. We can use these for filtering and for informing the user/agent about result distribution.

---

## 2. Available document fields (from `fl` default)

```
id, url_slug, title, main_content, product, resourceName, documentation_version,
pdf_path, documentKind, score, lastModifiedDate,
portal_product_names, view_uri, portal_advisory_type, allTitle,
portal_summary, portal_synopsis, portal_severity, portal_publication_date,
uri, portal_product, portal_product_variant, portal_product_version,
portal_product_platform, portal_architecture, portal_product_minor,
portal_product_filter,
cve_publicDate, cve_threatSeverity, cve_details
```

Additional fields discovered from actual responses:
```
heading_h2, stream_content_type, content, doc_id, timestamp, _version_
```

### Fields our code currently uses vs. ignores

| Field | Currently used? | Value for RAG |
|-------|----------------|---------------|
| `title` | Yes | High -- document title |
| `main_content` | Yes (via highlighting) | High -- main document text |
| `url_slug` | Yes | Medium -- URL identifier |
| `resourceName` | Yes | Medium -- file path on OKP |
| `documentKind` | Yes (stored but not surfaced) | High -- guide, solution, errata, article |
| `score` | **No** | High -- Solr relevance score |
| `product` | **No** | High -- product name for filtering/context |
| `documentation_version` | **No** | High -- version for filtering |
| `lastModifiedDate` | **No** | Medium -- recency signal |
| `view_uri` | **No** | High -- URL for citation |
| `portal_summary` | **No** | Medium -- short summary |
| `portal_synopsis` | **No** | Medium -- errata synopsis |
| `portal_severity` | **No** | Medium -- security severity |
| `heading_h2` | **No** | Medium -- document structure |
| `portal_product_names` | **No** | Medium -- all product names |

---

## 3. Available request handlers

| Handler | Path | Purpose |
|---------|------|---------|
| Main search | `/solr/portal/select` | edismax, faceted, highlighted (PRIMARY) |
| Errata search | `/solr/portal/select-errata` | Errata-specific fields and boosting |
| Simple query | `/solr/portal/query` | Basic indented JSON query |
| Browse | `/solr/portal/browse` | Velocity template-based (HTML output) |
| Elevate | `/solr/portal/elevate` | Promoted/boosted results |

---

## 4. What our current code does wrong

| Issue | Current behavior | What OKP actually does | Fix |
|-------|-----------------|------------------------|-----|
| Sends `hl.fragsize=300` | Overrides OKP default | OKP default is 150 (tuned) | Stop overriding; use OKP defaults |
| Sends `hl.fl=main_content,title` | Limits highlighting to 2 fields | OKP highlights 6 fields | Stop overriding; use OKP defaults |
| Strips `<em>` tags | Regex targets `<em>` | OKP uses `<b>` tags | Fix regex or use proper HTML entity decoding |
| Ignores `score` field | Not captured | Solr returns relevance score | Capture and expose in OKPDocument |
| Ignores `product` field | Not captured | Available in every response | Capture for filtering and context |
| Ignores `documentation_version` | Not captured | Available in every response | Capture for filtering and context |
| Ignores `view_uri` | Not captured | Linkable URL for citation | Capture for LLM citation |
| Ignores facet counts | Not parsed | Available in every response | Parse and expose for filtering UI/agent |
| Ignores `lastModifiedDate` | Not captured | Available for recency | Capture for recency ranking |
| Sends `wt=json` | Explicitly sets format | OKP default is already JSON | Not harmful but unnecessary |
| Ignores HTML entities in highlights | Only strips tags | `hl.encoder=html` produces entities | Decode HTML entities after tag stripping |
| No filter queries (`fq`) | No filtering support | Solr supports `fq=product:"OpenShift"` | Add `fq` parameter support |

---

## 5. Recommendations for production implementation

1. **Minimize parameter overrides** -- Only send `q`, `rows`, and `fq` (filter queries). Let OKP's tuned edismax defaults handle field boosting, phrase matching, faceting, and highlighting.

2. **Decode HTML entities** -- After stripping `<b>` tags, decode HTML entities (`html.unescape()`).

3. **Capture all useful fields** -- `score`, `product`, `documentation_version`, `view_uri`, `lastModifiedDate`, `portal_summary`, `heading_h2`.

4. **Expose facet counts** -- Parse `facet_counts` from the response and include in `RetrieveResult` for filtering and result distribution.

5. **Support filter queries** -- Map product/version/kind filters to Solr `fq` parameters.

6. **Use `view_uri` for citations** -- Include source URLs in context so the LLM can cite.
