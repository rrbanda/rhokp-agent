# Plan 4: AI Architect Review

**Perspective:** AI / ML engineer evaluating the retrieval pipeline for production RAG and agentic use
**Core question:** Is the retrieval pipeline effective enough to produce grounded, accurate LLM responses?
**Scope:** Query processing, retrieval quality, context construction, reranking, LLM integration, agent framework adapters
**Date:** 2026-02-28

---

## 1. Current Retrieval Pipeline

### 1.1 Pipeline diagram

```
User query (natural language)
         │
         ▼
  ┌──────────────┐
  │ No query     │    Query passed directly to Solr
  │ preprocessing│    as-is (no rewriting, no expansion)
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ Solr keyword  │    GET /solr/portal/select?q={query}
  │ search        │    &hl=true&hl.fl=main_content,title
  │               │    &hl.snippets=2&hl.fragsize=300
  │               │    &rows={rows}&wt=json
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ Parse Solr   │    Extract docs from response.docs
  │ response     │    Extract snippets from highlighting
  │              │    Strip <em> tags via regex
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ Build context│    "[1] Title\nSnippet\n\n[2] Title\nSnippet"
  │ (numbered    │    No scores, no URLs, no dedup
  │  list)       │
  └──────┬───────┘
         │
         ▼
  RetrieveResult(query, num_found, docs, context)
```

### 1.2 What this pipeline does well

| Aspect | Assessment |
|--------|-----------|
| Simplicity | Minimal moving parts; easy to understand and debug |
| Latency | Single HTTP call to Solr; no additional processing stages |
| Determinism | Same query always produces the same results (no ML model in the loop) |
| Solr highlighting | Leverages Solr's native highlighting, which is efficient and accurate |
| Typed output | `OKPDocument` dataclass with title, snippet, url_slug, resource_name, document_kind |

### 1.3 What this pipeline lacks (gap analysis)

```
Production RAG pipeline:

User query
    │
    ▼
┌───────────────┐
│ Query         │  ◄── MISSING: rewriting, expansion, intent detection
│ preprocessing │
└───────┬───────┘
        │
   ┌────▼────┐
   │ Keyword  │  ◄── EXISTS: Solr search (current)
   │ search   │
   └────┬────┘
        │            ┌─────────────┐
        │            │ Semantic    │  ◄── MISSING: embedding-based retrieval
        │            │ search      │
        │            └──────┬──────┘
        │                   │
   ┌────▼───────────────────▼──────┐
   │ Merge / hybrid fusion         │  ◄── MISSING: RRF, weighted fusion
   └───────────┬───────────────────┘
               │
   ┌───────────▼───────────────────┐
   │ Reranking                     │  ◄── MISSING: cross-encoder, MMR
   └───────────┬───────────────────┘
               │
   ┌───────────▼───────────────────┐
   │ Filtering / deduplication     │  ◄── MISSING: by product, version, recency
   └───────────┬───────────────────┘
               │
   ┌───────────▼───────────────────┐
   │ Token-budget-aware            │  ◄── MISSING: fit context to model window
   │ context construction          │
   └───────────┬───────────────────┘
               │
   ┌───────────▼───────────────────┐
   │ Citation-enabled context      │  ◄── MISSING: source URLs, doc references
   └───────────┬───────────────────┘
               │
               ▼
        LLM prompt
```

---

## 2. Detailed Findings

### 2.1 No query preprocessing

**Severity: High**
**Impact: Retrieval recall and precision are limited by exact keyword matching**

The user's natural language query is passed directly to Solr's default query parser. This means:

- **"How do I fix OOM kills in OpenShift?"** -- Solr matches on "OOM", "kills", "OpenShift" as individual terms. It does not understand that "OOM kills" is a compound concept, or that "Out of Memory" is a synonym.
- **"pod eviction troubleshooting"** vs. **"my pods keep getting evicted"** -- These express the same intent but have very different keyword overlap.
- **Stop words** -- Solr's default query parser may match on "do", "I", "in" which dilute relevance.
- **Solr special characters** -- Queries containing `+`, `-`, `&&`, `||`, `!`, `(`, `)`, `{`, `}`, `[`, `]`, `^`, `"`, `~`, `*`, `?`, `:`, `\` are interpreted as Solr syntax, not as literal search terms.

**Recommended improvements:**

1. **Query sanitization:** Escape Solr special characters to prevent injection and syntax errors
2. **Query normalization:** Lowercase, strip extra whitespace (partially done with `.strip()`)
3. **Synonym expansion:** Map common terms ("OOM" -> "Out of Memory OR OOM", "k8s" -> "Kubernetes")
4. **Optional: LLM-based query rewriting:** Use the LLM to rewrite natural language into effective keyword queries (e.g., "How do I fix OOM kills?" -> "OpenShift pod OOMKilled troubleshoot memory limits")

### 2.2 Keyword-only search: no semantic retrieval

**Severity: High**
**Impact: Misses documents that are semantically relevant but use different vocabulary**

The current pipeline relies entirely on Solr's keyword search with BM25-style relevance. This is a known limitation for documentation retrieval:

| Query type | Keyword search effectiveness |
|-----------|------------------------------|
| Exact term match ("install OpenShift 4.15") | Good |
| Synonym mismatch ("container runtime" vs "CRI-O") | Poor |
| Conceptual query ("best practices for securing a cluster") | Poor |
| Abbreviation mismatch ("OCP" vs "OpenShift Container Platform") | Poor |
| Multi-concept ("RBAC and network policies for multi-tenant") | Moderate |

**Options for improvement (in order of complexity):**

1. **Solr synonym filter** -- Configure Solr's `synonyms.txt` to map common Red Hat term variants. Low effort, improves recall for known synonyms. Requires OKP Solr config access.
2. **Solr `edismax` query parser** -- Switch from default parser to `edismax` with `qf` (query fields) and `mm` (minimum match) tuning. Better multi-field relevance. Low effort.
3. **Hybrid retrieval** -- Add a vector store (e.g., Chroma, Qdrant) alongside OKP. Embed OKP document titles/snippets. At query time, run both keyword (Solr) and semantic (vector) search, fuse results with Reciprocal Rank Fusion (RRF). Medium effort.
4. **Full semantic search** -- Embed all OKP documents and query a vector store. Higher recall for conceptual queries. High effort; requires embedding pipeline and index maintenance.

**Recommendation:** Start with option 2 (`edismax` with tuned `qf`/`mm`), then add option 3 (hybrid with RRF) as the next major iteration.

### 2.3 No reranking

**Severity: Medium**
**Impact: The top-K results may not be the most relevant for the specific query**

Solr returns results in BM25 relevance order, which is decent for keyword queries but not optimal for RAG. Production RAG systems typically add a reranking stage:

| Reranking approach | Quality improvement | Latency cost | Complexity |
|-------------------|--------------------|--------------|-----------| 
| Cross-encoder (e.g., `ms-marco-MiniLM`, `bge-reranker`) | High | 50-200ms for 10 docs | Medium |
| Maximal Marginal Relevance (MMR) | Moderate (diversity) | Minimal | Low |
| LLM-based reranking | High | 1-5s | High |
| Reciprocal Rank Fusion (multiple sources) | Moderate | Minimal | Medium |

**Recommendation:** Add optional cross-encoder reranking as a post-retrieval step. Make it configurable (off by default for latency-sensitive use cases, on for quality-sensitive use cases). A good default reranker is `BAAI/bge-reranker-v2-m3` or `cross-encoder/ms-marco-MiniLM-L-12-v2`.

### 2.4 Context construction is naive

**Severity: High**
**Impact: The LLM receives suboptimal context, leading to worse answers and no citation ability**

```python
def _build_context(docs: list[OKPDocument]) -> str:
    parts = [f"[{i}] {doc.title}\n{doc.snippet}" for i, doc in enumerate(docs, 1)]
    return "\n\n".join(parts)
```

This produces:
```
[1] Installing OpenShift
How to install the product on bare metal...

[2] Upgrade Notes
Steps to upgrade from 4.14 to 4.15...
```

**Problems:**

1. **No source URLs** -- The LLM cannot cite where information came from. `url_slug` is available in the data but not included in context.
2. **No document kind** -- The LLM cannot distinguish a "guide" from a "release note" from a "solution article."
3. **No relevance indicator** -- All snippets appear equally authoritative.
4. **No deduplication** -- If Solr returns multiple snippets from the same document, they all appear as separate entries, wasting context budget.
5. **No truncation awareness** -- Snippets may be cut mid-sentence (Solr `hl.fragsize=300`), and the 500-char hard limit adds a second truncation point.
6. **No token budget** -- The context is built without knowing how many tokens the LLM can accept. For `rows=5` with short snippets, this is fine. For `rows=50`, the context could exceed the model's window.

**Recommended context format:**

```
[1] Installing OpenShift (Guide) — /docs/installing-openshift
How to install the product on bare metal. Ensure your nodes meet
the minimum hardware requirements before proceeding.

[2] Upgrade Notes (Release Note) — /docs/upgrade-notes-4.15
Steps to upgrade from 4.14 to 4.15. Back up your etcd before starting
the upgrade process.
```

**Additional improvements:**
- Add a `max_tokens` parameter that estimates token count and truncates context to fit
- Deduplicate snippets from the same source document
- Optionally format as JSON for structured LLM consumption

### 2.5 Solr highlighting parameters are untuned

**Severity: Medium**
**Impact: Snippet quality may be suboptimal**

```python
"hl.snippets": 2,      # Return 2 highlight snippets per document
"hl.fragsize": 300,     # Each snippet is max 300 characters
```

These are default-ish values with no documented rationale:

- **`hl.snippets=2`** -- But only the first snippet is used (line 158: `[:1]`). The second snippet is requested from Solr but discarded. This wastes Solr processing time.
- **`hl.fragsize=300`** -- 300 characters is roughly 75 tokens. For dense technical documentation, this may cut off important instructions. For simple definitions, 300 chars may be too much.
- **No `hl.encoder`** -- The default encoder may not handle special characters well.
- **No `hl.maxAnalyzedChars`** -- Solr defaults to analyzing the first 51,200 characters of a field. Long documents may have relevant content beyond this limit.

**Recommendation:** Tune these parameters empirically against real OKP data:
1. Change `hl.snippets` to 1 (since only 1 is used) or use both snippets in context
2. Test `hl.fragsize` at 200, 300, 500, and 800 to find the best trade-off
3. Set `hl.maxAnalyzedChars` explicitly based on OKP document sizes
4. Consider using Solr's `UnifiedHighlighter` for better snippet quality

### 2.6 No filtering or faceting

**Severity: High**
**Impact: Users cannot scope searches to specific products, versions, or document types**

The Solr query uses only `q` (query) and `rows`. OKP's Solr schema likely has fields for:
- Product name (e.g., "OpenShift Container Platform", "RHEL")
- Version (e.g., "4.15", "9.4")
- Document kind (e.g., "guide", "solution", "release_note")
- Language

None of these are exposed as filters. A query for "install OpenShift" returns results from all products and all versions. In a production setting:
- A user asking about OpenShift 4.15 does not want RHEL 8 results
- A user wanting installation guides does not want release notes
- Filtering reduces noise and improves RAG answer quality

**Recommendation:** Add `filter` parameter to `retrieve()` that maps to Solr `fq` (filter query):

```python
result = retrieve(
    "install OpenShift",
    filter={"documentKind": "guide", "product": "openshift-container-platform"},
    rows=5,
)
```

Expose this through LangChain's `search_kwargs` and MCP tool parameters.

### 2.7 LangChain adapter: missing production features

**Severity: Medium**

| Feature | Standard LangChain retrievers | OKPLangChainRetriever |
|---------|------------------------------|----------------------|
| `search_type` (similarity, mmr, threshold) | Yes | No |
| `search_kwargs` (k, filter, etc.) | Yes | No |
| Callback manager (`run_manager`) | Yes | No |
| Configurable via `RunnableConfig` | Yes | No |
| Async using native async client | Yes | No (uses `asyncio.to_thread`) |
| Metadata in results | Common | Partial (4 fields) |
| Score in metadata | Common | No |

**Recommendation:** Implement `search_kwargs` passthrough (map `k` to `rows`, `filter` to Solr `fq`). Accept `run_manager` in `_get_relevant_documents` to enable LangSmith tracing. Use `aretrieve()` in `_aget_relevant_documents` instead of `asyncio.to_thread`.

### 2.8 MCP tool: description lacks retrieval metadata

**Severity: Medium**

```python
@mcp.tool
def search_red_hat_docs(query: str) -> str:
    """Search the Red Hat Offline Knowledge Portal for product documentation,
    solutions, and how-to guides. Use this when the user asks about Red Hat
    products, OpenShift, RHEL, or other Red Hat technologies.

    Args:
        query: Search query (e.g. 'how to install OpenShift',
               'RHEL kernel tuning')
    """
```

This tool description is reasonable for basic use, but for production agentic use:

1. **No parameters beyond `query`** -- The agent cannot specify product, version, or result count
2. **No structured output** -- The agent gets a plain text string, not structured data it can reason about
3. **No result metadata** -- The agent cannot tell how many results were found or assess confidence
4. **No "when NOT to use" guidance** -- The agent may call this tool for non-Red-Hat questions

**Recommendation:** Expand the tool signature:

```python
@mcp.tool
def search_red_hat_docs(
    query: str,
    product: str | None = None,
    max_results: int = 5,
) -> str:
    """Search Red Hat Offline Knowledge Portal for official product documentation.

    Returns numbered documentation excerpts with source references.
    Results are keyword-matched; for best results, use specific product
    terminology rather than natural language questions.

    Only use this tool for questions about Red Hat products (OpenShift, RHEL,
    Ansible, etc.). Do not use for general programming or non-Red-Hat topics.

    Args:
        query: Search terms (e.g., 'OpenShift 4.15 bare metal install',
               'RHEL 9 kernel tuning parameters')
        product: Optional product filter (e.g., 'openshift-container-platform',
                 'rhel'). Omit to search all products.
        max_results: Maximum number of documentation excerpts to return (1-20).
    """
```

### 2.9 No ADK (Agent Development Kit) integration

**Severity: Medium**
**Impact: Cannot use this retriever with Google's ADK or other emerging agent frameworks**

The project only has a LangChain adapter. The AI agent ecosystem is fragmented across:
- **LangChain** (dominant today)
- **LlamaIndex** (strong in retrieval)
- **Google ADK** (emerging, production-backed by Google)
- **CrewAI** (multi-agent)
- **AutoGen** (Microsoft)
- **Direct MCP** (framework-agnostic via MCP protocol)

The MCP server provides framework-agnostic access (any MCP client can use it). The LangChain adapter provides deep LangChain integration. But for the growing ADK ecosystem, there is no adapter.

**Recommendation:** Prioritize based on target users:
1. MCP covers the framework-agnostic case (already done)
2. LangChain covers the dominant RAG framework (already done, needs improvement)
3. ADK adapter should be next if Google ADK is a target platform
4. LlamaIndex adapter for retrieval-heavy use cases

### 2.10 Prompt engineering in the reference client is basic

**Severity: Medium**

```python
system_content = (
    "You are a Red Hat expert. Answer the user's question using ONLY the following "
    "documentation excerpts. If the excerpts do not contain enough information, say so. "
    "Do not invent details."
)
user_content = f"Documentation excerpts:\n\n{result.context}\n\nQuestion: {question}"
```

For production RAG:
- **No citation format instructions** -- The LLM is not told how to reference sources
- **No output structure** -- The LLM is not told to format the answer in any particular way
- **No confidence/hedging guidance** -- Beyond "say so," no instruction on how to express uncertainty
- **No few-shot examples** -- The LLM has no model of what a good answer looks like
- **No grounding verification** -- No instruction to distinguish between information from excerpts vs. pre-training knowledge
- **Prompt is not versioned** -- Changes to the prompt are not tracked

**Recommendation:** Create a prompt template module with versioned prompts:

```python
SYSTEM_PROMPT_V1 = """You are a Red Hat technical expert. Answer the user's question
using ONLY the documentation excerpts provided below.

Rules:
1. Cite sources using [N] notation (e.g., "According to [1], ...").
2. If the excerpts do not contain sufficient information, explicitly state:
   "The available documentation does not cover this topic."
3. Do not use knowledge from your training data. Only use the excerpts.
4. If multiple excerpts conflict, present both and note the discrepancy.
5. Format your answer with clear headings and steps where appropriate.
"""
```

---

## 3. Retrieval Quality Assessment

### 3.1 Expected failure modes with current pipeline

| Scenario | Expected behavior | Actual behavior | Risk |
|----------|------------------|-----------------|------|
| Query uses synonyms not in OKP | Miss relevant docs | Returns irrelevant or no results | High |
| Query is very broad ("OpenShift") | Returns most popular docs | May return random highly-linked docs | Medium |
| Query about specific version | Returns all versions | No version filtering possible | High |
| Query with Solr special chars | Correct search | Solr syntax error or injection | Critical |
| Same query repeated in conversation | Fresh retrieval each time | No caching; unnecessary OKP load | Medium |
| 50 results requested | 50 snippets in context | Context exceeds LLM token limit | High |
| OKP returns HTML-heavy snippets | Clean text | Regex strips tags but not entities | Medium |
| Query in non-English | Search in English index | No results or wrong results | Low |

### 3.2 Benchmarking needs

There is no way to measure retrieval quality today. Production RAG systems need:

1. **Evaluation dataset** -- A set of (query, expected_relevant_documents) pairs from real OKP data
2. **Retrieval metrics** -- Precision@K, Recall@K, NDCG@K, Mean Reciprocal Rank (MRR)
3. **End-to-end metrics** -- Answer correctness, faithfulness, relevance (using an LLM-as-judge or human evaluation)
4. **A/B testing infrastructure** -- Compare pipeline changes (e.g., with vs. without reranking)

**Recommendation:** Create an `eval/` directory with:
- A small evaluation dataset (20-50 queries with expected relevant documents)
- A script that runs retrieval and computes Precision@5 and MRR
- This becomes the regression test for retrieval quality changes

---

## 4. Roadmap: From Keyword Search to Production RAG

### Phase 1: Harden existing keyword retrieval (1-2 weeks)

1. Add query sanitization (escape Solr special characters)
2. Switch to `edismax` parser with `qf` (query fields) and `mm` (minimum match)
3. Add `filter` parameter for product/version/document-kind filtering
4. Improve context construction: add source URLs, document kind, deduplication
5. Add `max_tokens` parameter to `_build_context()` for token-budget awareness
6. Fix LangChain async to use `aretrieve()`
7. Expand MCP tool signature with `product` and `max_results` parameters

### Phase 2: Retrieval quality measurement (1 week)

1. Create evaluation dataset from real OKP queries
2. Implement Precision@K and MRR evaluation script
3. Establish baseline metrics for current keyword-only pipeline
4. Add retrieval quality check to CI (regression guard)

### Phase 3: Reranking (1 week)

1. Add optional cross-encoder reranking stage
2. Add MMR (maximal marginal relevance) for result diversity
3. Measure quality improvement vs. baseline (Phase 2 metrics)
4. Make reranking configurable (off for latency-sensitive, on for quality-sensitive)

### Phase 4: Hybrid retrieval (2-3 weeks)

1. Add embedding pipeline for OKP documents (titles + first N chars of content)
2. Add vector store (Chroma for embedded, Qdrant for standalone)
3. Implement Reciprocal Rank Fusion (RRF) to merge keyword + semantic results
4. Measure quality improvement vs. keyword-only baseline
5. Make hybrid retrieval configurable (keyword-only, semantic-only, hybrid)

### Phase 5: Advanced (ongoing)

1. LLM-based query rewriting (turn natural language into effective keyword queries)
2. Conversational retrieval (use conversation history to refine queries)
3. ADK adapter
4. Structured output from LLM (citations, confidence scores)
5. Retrieval feedback loop (log which results were used by the LLM)

---

## 5. Scorecard

| Area | Rating | Key gap |
|------|--------|---------|
| Retrieval method | Needs Work | Keyword-only; no semantic, no hybrid |
| Query preprocessing | Fail | No sanitization, no expansion, no rewriting |
| Result quality | Needs Work | No reranking, no filtering, no deduplication |
| Context construction | Fail | No citations, no token awareness, no structure |
| LangChain integration | Needs Work | Missing callbacks, search_kwargs, proper async |
| MCP tool design | Needs Work | No filtering params, returns unstructured strings |
| Agent framework coverage | Needs Work | LangChain + MCP only; no ADK, no LlamaIndex |
| Prompt engineering | Needs Work | Basic prompt; no citations, no versioning |
| Evaluation / metrics | Fail | No evaluation dataset, no retrieval quality metrics |
| Solr query optimization | Needs Work | Default parser, untuned highlighting |

---

## 6. Verdict: Refactor or Rewrite?

**Retrieval core (`retrieve.py`):** Refactor. The HTTP client logic, error handling, and data models are sound. The Solr query construction needs to be parameterized (edismax, filters) and the response parsing needs defensive hardening. Keep the structure, evolve the implementation.

**Context construction:** Rewrite. `_build_context()` is too simplistic for production RAG. Replace with a token-aware, citation-enabled context builder in a dedicated module (`context.py`).

**LangChain adapter:** Refactor. Add callbacks, search_kwargs, and proper async. The class structure is correct.

**MCP tool:** Refactor. Expand the tool signature and return structured data. The FastMCP setup is correct.

**Reference client (`ask_okp.py`):** Rewrite. The prompt engineering, response parsing, and error handling are all below production grade. Either promote to a proper CLI command with well-engineered prompts, or extract the LLM integration into a reusable module.

**Evaluation infrastructure:** Build from scratch. Nothing exists. This is the most important gap for long-term retrieval quality.
