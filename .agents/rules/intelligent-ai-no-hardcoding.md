---
name: intelligent-ai-no-hardcoding
description: Non-negotiable directive forbidding hardcoded cities, domains, ATS lists, and regex signal dictionaries. Enforces dynamic algorithmic derivation and LLM semantic reasoning.
always_on: true
---

# Intelligent Agentic AI - Zero Hardcoding Rule

1. **NO Hardcoded Entity Dictionaries**:
   - Do NOT embed lists of cities, countries, companies, or domain names in python files.
   - Extract location from the job posting/email text directly using structural hints or LLM reasoning.
   - Extract channel/source dynamically by stripping TLDs and subdomains from sender emails or URLs.

2. **NO Hardcoded Keyword Signal Tables**:
   - Do NOT maintain regex lists for "interview signals" or "rejection signals".
   - Use LLM semantic reasoning (`llm_provider`) to understand natural language intent.

3. **Intelligent QA Validator**:
   - The QA layer must use semantic LLM verification, not brittle string searching.
   - If an extraction is ambiguous, ask the LLM to verify or flag it for user review.
