# AGENTS.md - Core Project Directives

## CRITICAL: Intelligent Agentic AI vs. Brittle Hardcoded Engines

This project is an **intelligent agentic AI helper**, NOT a brittle heuristic rule engine.
Every code change must adhere to these non-negotiable principles:

---

### 1. Zero Hardcoding of Real-World Entities
- **NEVER hardcode lists of cities, countries, or regions** (e.g., no `CITIES = ["Berlin", "Frankfurt", ...]`).
  - *Why*: A hardcoded list covers 1% of entities while 99% fail or hit fallbacks. It creates unmaintainable bloat requiring continuous manual updates.
  - *Proper Solution*: Extract location directly from the job application text, structured fields (`Location:`, `Ort:`), or use the LLM to understand geographical references in context.
- **NEVER hardcode preset lists of job boards or ATS platforms** (e.g., no `CHANNEL_RULES = [("ashbyhq.com", ...), ...]`).
  - *Why*: Thousands of job boards and ATS platforms exist worldwide and new ones emerge daily.
  - *Proper Solution*: Dynamically derive the platform name from the domain or URL (e.g., stripping TLDs and subdomains: `recruiting@personio.de` → `Personio`, `ashbyhq.com` → `Ashbyhq`), or load external user-configurable aliases.
- **NEVER hardcode keyword signal arrays for classification** (e.g., no `REJECTION_SIGNALS = ["leider müssen wir", "we regret to inform", ...]`).
  - *Why*: Real correspondence in German, English, and other languages varies infinitely. Regex lists always fail on new phrasings and hallucinate on negation.
  - *Proper Solution*: Use LLM semantic reasoning (`llm_provider`) with chain-of-thought to classify emails, assess sentiment, and verify intent.

---

### 2. Intelligent Generalized QA Validation
- The QA validation step must rely on **multimodal or semantic LLM reasoning**, not regex pattern matching.
- An AI agent verifies extractions by asking:
  - Does the company name make sense given the full sender and body context?
  - Does the text actually confirm an interview, or is it a general inquiry or rejection?
- If an LLM call is unavailable or in offline mode, fall back to generalized domain parsing, never brittle hardcoded language tables.

---

### 3. Architecture & Simplicity
- Keep code simple, clean, and dynamic.
- Prefer 10 lines of clean dynamic logic (e.g., domain extraction) over 100 lines of regex dictionaries.
- Externalize all configurable aliases to JSON files under `resources/` or `config.json`.
