# Checklist: Does the RHOKP product overview prevent a public example repo?

Use this checklist while reading the **Red Hat Offline Knowledge Platform (RHOKP) – product overview (rolling updates)** PDF. It helps identify anything that would **prevent** or **restrict** publishing an example like this repo (code that retrieves from OKP and exposes an MCP tool / ADK agent with Llama Stack).

**Note:** The PDF could not be read automatically from the path provided. Work through the sections below with the document open and tick or note findings.

---

## 1. Confidentiality and distribution

| Check | What to look for in the PDF | Blocks public repo? |
|-------|------------------------------|----------------------|
| Document classification | "Red Hat Confidential," "Internal only," "Partner only," "NDA required" | Document itself must not be in the repo. Does **not** by itself forbid a **separate** public code example that only uses public APIs. |
| OKP product name | Any text saying the **product name** "Red Hat Offline Knowledge Portal" / "OKP" / "RHOKP" must not be used in public materials | If yes, we’d need to avoid or genericize the product name in README/docs (e.g. "a Red Hat documentation portal"). |
| Code / integration examples | "Do not publish code that integrates with OKP" or "Sample code is internal only" | **Yes** – would prevent a public git repo that shows OKP integration. |
| APIs and interfaces | "Solr API / search API is internal" or "Do not document or expose API usage publicly" | **Yes** – would prevent showing retrieval code that calls the search endpoint. |

**Your notes:**
- [ ] Document classification (quote exact phrase): _______________________
- [ ] Any "do not publish" or "internal only" for code/examples: _______________________
- [ ] Any restriction on using the product name in public: _______________________

---

## 2. Technical and security

| Check | What to look for in the PDF | Blocks public repo? |
|-------|------------------------------|----------------------|
| ACCESS_KEY / decryption | Describing how ACCESS_KEY works (decrypt content at rest) | **No** – our repo does **not** implement or ship ACCESS_KEY; we only document "pass at runtime" for the **OKP container**. Safe to describe that pattern in general terms. |
| Paywalled content | "Paywalled content must not leave the environment" or "Do not send context to third parties" | **No** – our repo doesn’t ship content; it only shows how to **query** an OKP instance the user runs. User is responsible for where they send retrieved context (e.g. Llama Stack). |
| Architecture diagrams | "Architecture diagrams are confidential" | **No** – we don’t copy Red Hat diagrams; we have our own minimal flow in `docs/architecture.md`. |
| Roadmap / future plans | Unreleased features, dates, roadmap details | **Yes** if we put that in the repo. We should **not** copy roadmap content; our repo describes current usage only. |

**Your notes:**
- [ ] Any mention that integration code must stay internal: _______________________
- [ ] Any "do not share with third parties" that would apply to publishing open-source code: _______________________

---

## 3. Trademarks and branding

| Check | What to look for in the PDF | Action if found |
|-------|------------------------------|------------------|
| Red Hat / OKP marks | "Use of Red Hat trademarks in open source projects must follow …" or "Contact legal before …" | Note the requirement; often a disclaimer ("not officially supported by Red Hat") is enough. We can add that to README. |
| "Official" or "supported" | Any note that only Red Hat can claim "official" or "supported" | We already avoid claiming the repo is official; we can add an explicit disclaimer. |

**Your notes:**
- [ ] Trademark or branding guidance: _______________________

---

## 4. What this repo actually contains (for comparison)

When in doubt, compare the PDF’s restrictions to what the repo does:

- **Does not contain:** OKP product binaries, paywalled content, ACCESS_KEY implementation, internal architecture diagrams, roadmap, or confidential product details.
- **Does contain:** Code that calls OKP’s **search API** (public HTTP endpoint when the user runs OKP), an MCP server that exposes one search tool, and an ADK agent that sends retrieved context to an LLM. All configuration via env vars; no secrets.

So the question for the PDF is: **Does it forbid or restrict “publishing an open-source example that calls the OKP search API and shows MCP/agent usage?”** If the PDF only restricts **confidential docs**, **roadmap**, or **content**, and does **not** forbid **integration examples** or **public use of the product name**, then a public repo like this is typically OK.

---

## 5. Summary decision

After reviewing the PDF:

- [ ] **No blockers found** – Nothing in the document prevents publishing this example repo. (Optional: add README disclaimer that the project is community/example, not officially supported by Red Hat.)
- [ ] **Blockers found** – List them here and decide with legal/product:
  - _______________________________________________________
  - _______________________________________________________
- [ ] **Unclear** – Schedule a short check with Red Hat (e.g. OKP product owner or legal): "Can we publish a public git repo that demonstrates OKP retrieval + MCP + Llama Stack agent, with no secrets and only public API usage?"

---

## 6. Optional README disclaimer (if you go public)

If you make the repo public, you can add this (or similar) to the top of README:

```markdown
This project is community tooling and is not officially supported by Red Hat.
It demonstrates integration with Red Hat Offline Knowledge Portal (OKP) for use with AI agents (e.g. Llama Stack).
```

This makes the status clear and is consistent with typical Red Hat open-source guidance.
