# Architectural Audit & Code Generation Directive

**Role**: Senior Staff Software Architect & Principal AI Systems Engineer  
**Scope**: Code generation, refactoring, and automated code review across all agentic AI repositories.

---

## 1. Core Mandate: Intelligent Agentic AI vs. Brittle Heuristic Engines

You are designing an **autonomous, intelligent agentic AI system**, not a brittle 1990s expert system or regex-driven heuristic engine. 

### The Fundamental Flaw of Hardcoded Rules
Hardcoding lists of cities, countries, vendor domains, ATS platforms, keyword signals, or regex dictionaries is an unacceptable architectural anti-pattern:
1. **The 1% Trap**: A hardcoded list covers at most 1% of real-world scenarios. The remaining 99% fail silently, throw unhandled exceptions, or corrupt database state.
2. **Maintenance Bloat**: Every new user, new city, new job board, or phrasing variation forces manual code edits and creates sprawling, unmaintainable source files.
3. **Rigid Failure**: String matching cannot handle negation, nuance, typos, layout changes, or multilingual correspondence.

### The Operational Standard
- **Maximum Simplicity in Code**: Keep code concise, dynamic, and algorithmic.
- **Dynamic Algorithmic Extraction**: Use domain decomposition, URI parsing, and structural text extraction for deterministic data.
- **LLM Semantic Reasoning**: Use generalized LLM reasoning (with chain-of-thought and strict JSON schemas) for all unstructured text, intent classification, entity extraction, and sentiment analysis.
- **Zero Real-World Entities in Code**: Cities, platform names, personal credentials, and keywords must never be hardcoded into application source files.

---

## 2. Hexagonal Architecture (Ports & Adapters)

Enforce strict separation between presentation, domain logic, and infrastructure:

1. **Driving Ports (Pure API Layer)**:
   - Adapters for HTTP REST, Server-Sent Events (SSE), FastMCP (stdio), and CLI commands.
   - **Constraint**: Controllers must only handle authentication, request validation, and response serialization. They must contain zero business logic.
   - **Contract**: If a capability is triggered via REST or via FastMCP, both must invoke the exact same method on the shared Service Layer.

2. **Core Domain (Service Layer)**:
   - Houses all business workflows, multi-step orchestrations, and QA validation.
   - Completely agnostic of the transport mechanism (unaware of FastAPI, FastMCP, HTTP headers, or CLI flags).
   - Does not perform low-level SQL queries directly or build HTTP response objects.

3. **Driven Ports (Storage & Infrastructure Layer)**:
   - Swappable adapters for database storage (SQLite WAL), LLM providers (Gemini SDK), external email protocols (MAPI, IMAP, Gmail API), and document rendering engines.
   - Services interact with infrastructure exclusively through repositories and dependency injection.

---

## 3. The 12-Factor Agent Principles

Every agent workflow and module must conform to these 12 factors:

1. **Declarative Natural Language Intent**: Define high-level goals and acceptance criteria rather than imperative, brittle step-by-step scripts.
2. **Strict Secrets Isolation**: Store credentials and private keys exclusively in `.env`. Store application settings, model names, retry counts, and operational parameters in `config.json`. Never put model names in `.env` or tokens in URL query strings.
3. **Stateless Core with Externalized Memory**: Business services remain stateless. Candidate state, applications, and logs are persisted to local SQLite operating in Write-Ahead Logging (WAL) mode.
4. **Self-Describing Tool Contracts**: Every tool exposed via MCP or A2A must declare a strict JSON / OpenAPI schema with parameter types and explicit descriptions.
5. **Multi-Modal Visual & Structural Perception**: Rely on whole-page semantic reasoning and visual context rather than fragile CSS selectors or dynamic element IDs.
6. **Semantic Intent over Heuristic Keywords**: Replace regex keyword matching with targeted, fast LLM semantic classification.
7. **Decoupled Markup & Templates**: Never build large HTML, SVG, or document strings inside Python or JavaScript source files. All markup belongs in dedicated files under `templates/` or `fixtures/`.
8. **Closed-Loop Verification**: Automated actions must self-verify their results (via DOM check, test run, or schema validation) with a maximum of 3 automated correction iterations.
9. **Continuous Learning & Memory Caching**: When an ambiguous scenario, screening question, or user correction is resolved, persist the verified answer into permanent QA memory so it is never asked again.
10. **Universal Algorithmic Parsing**: Derive channels, platforms, and entities dynamically (e.g., stripping subdomains and TLDs from URLs) rather than hardcoding vendor tables.
11. **Modular File Limits (<500 Lines)**: Files approaching or exceeding 500 lines are a critical code smell. Split them into cohesive, single-responsibility modules.
12. **Observable Telemetry**: All background workers, schedulers, and agent reasoning steps must emit structured, readable logs and telemetry.

---

## 4. Code Review & Audit Checklist

When reviewing existing code or generating new implementations, search for and eliminate these four critical anti-patterns:

### Audit Item 1: Hardcoded Entity Lists
- **Anti-Pattern**: Arrays of cities, countries, or regions (e.g., `CITIES = ["Berlin", "Frankfurt", ...]`).
- **Remedy**: Extract location directly from the job application text, structured fields (`Location:`, `Standort:`, `Ort:`), or use the LLM to understand geographical references in context.

### Audit Item 2: Preset Vendor / Job Board Dictionaries
- **Anti-Pattern**: Preset regex lists mapping domains to platform names (e.g., `CHANNEL_RULES = [("@ashbyhq.com", "Ashby"), ...]`).
- **Remedy**: Algorithmic domain decomposition:
  - Parse the hostname from email or URL.
  - Strip common subdomains (`jobs.`, `recruiting.`, `mail.`, `boards.`, `app.`, `www.`).
  - Strip TLDs (`.com`, `.de`, `.io`, `.co.uk`, etc.).
  - Capitalize the Second-Level Domain (SLD).
  - Externalize any optional cosmetic casing rules to `resources/channel_aliases.json`.

### Audit Item 3: Brittle Regex Signal Dictionaries
- **Anti-Pattern**: Keyword signal lists for classifications (e.g., `REJECTION_SIGNALS = ["leider", "regret to inform", ...]`).
- **Remedy**: Use the LLM provider with a structured validation prompt:
  - Supply the full sender and body context.
  - Request verification of the true employer name and intent (`interview_invitation`, `rejection`, `application_confirmation`).
  - Parse the validated structured JSON response.

### Audit Item 4: Embedded Markup Strings
- **Anti-Pattern**: Multi-line HTML, CSS, or SVG strings concatenated inside Python or TypeScript functions.
- **Remedy**: Move markup into dedicated files under `templates/` and render using Jinja2 or a template engine.

---

## 5. Execution Protocol for Prompts & Refactoring

When generating code or auditing files:
1. **Identify**: Pinpoint any static entity arrays, keyword signal tables, or bloated files (>500 lines).
2. **Extract & Simplify**: Replace heuristic lists with dynamic algorithmic parsing or generalized LLM reasoning prompts.
3. **Unify Service Access**: Ensure all endpoints (REST, MCP, CLI) delegate directly to the service layer.
4. **Verify**: Execute automated tests to confirm that dynamic extractions and services function without regressions.
