"""Cover Letter Generator Engine (DIN 5008 Standard).

Adheres to clean-code-architecture:
- Templates strictly separated into templates/cover_letter/ (never hardcoded in Python).
- Candidate PII loaded strictly from profile.local.json.
- Tailored engineer-to-engineer tone (anti-AI-slop) with Gemini Flash semantic reasoning.
- High-fidelity PDF rendering via Playwright.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.config import load_config
from src.core.llm_provider import call_gemini_semantic_analysis
from src.core.profile import CandidateProfile, load_profile

log = logging.getLogger(__name__)


class CoverLetterEngine:
    """Generates DIN 5008 compliant bilingual (German/English) cover letters."""

    def __init__(self, templates_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        root_dir = Path(__file__).resolve().parent.parent.parent
        self.templates_dir = templates_dir or (root_dir / "templates" / "cover_letter")
        self.output_dir = output_dir or (root_dir / "output" / "cover_letters")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_template_file(self, filename: str) -> str:
        path = self.templates_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Cover letter template not found at {path}")
        return path.read_text(encoding="utf-8")

    def generate(
        self,
        company: str,
        role: str,
        recipient_address: str = "",
        contact_person: str = "",
        lang: str = "de",
        use_gemini: bool = True,
        profile: Optional[CandidateProfile] = None,
    ) -> Dict[str, Any]:
        """Generates DIN 5008 HTML and PDF cover letters tailored to the target role.

        Returns:
            Dict with pdf_path, html_path, filename, company, role, generated_at.
        """
        prof = profile or load_profile()
        pers = prof.personal
        cand_name = pers.fullName or f"{pers.firstName or ''} {pers.lastName or ''}".strip() or "Candidate"

        comp_display = company.strip() if company else "Unternehmen"
        role_display = role.strip() if role else "Software Engineer"
        recipient_display = recipient_address.strip() if recipient_address else comp_display

        # Clean 1-word company identifier for filename
        raw_comp_word = comp_display.split()[0] if comp_display else "Company"
        comp_word = "".join(c for c in raw_comp_word if c.isalnum()).strip().capitalize() or "Company"

        now = datetime.now()
        month_abbr = now.strftime("%b")
        date_str = f"{now.day:02d}{month_abbr}{now.year}"
        prefix = "Anschreiben" if lang.lower().startswith("de") else "CoverLetter"
        base_name = f"{prefix}_{comp_word}_{date_str}"

        # Automatic versioning if file exists
        if not (self.output_dir / f"{base_name}.pdf").exists():
            out_name = base_name
        else:
            ver = 2
            while (self.output_dir / f"{base_name}_v{ver:02d}.pdf").exists():
                ver += 1
            out_name = f"{base_name}_v{ver:02d}"

        html_path = self.output_dir / f"{out_name}.html"
        pdf_path = self.output_dir / f"{out_name}.pdf"

        # 1. Format date (DIN 5008 format)
        de_months = [
            "Januar", "Februar", "März", "April", "Mai", "Juni",
            "Juli", "August", "September", "Oktober", "November", "Dezember"
        ]
        if lang.lower().startswith("de"):
            formatted_date = f"{now.day:02d}. {de_months[now.month - 1]} {now.year}"
        else:
            formatted_date = now.strftime("%d %B %Y")

        # 2. Build candidate contact line
        contact_parts = []
        if pers.street:
            contact_parts.append(pers.street)
        if pers.postalCode and pers.city:
            contact_parts.append(f"{pers.postalCode} {pers.city}")
        elif pers.address:
            contact_parts.append(pers.address)
        if pers.phone:
            contact_parts.append(f"Tel: {pers.phone}")
        if pers.email:
            contact_parts.append(f"E-Mail: {pers.email}")
        contact_line = " &bull; ".join(contact_parts)

        # 3. Determine body content (Gemini reasoning or template fallback)
        body_text = None
        if use_gemini and os.getenv("GEMINI_API_KEY"):
            try:
                log.info("Generating customized cover letter with Gemini Flash for '%s' at '%s'...", role_display, comp_display)
                skills_list = prof.technical_skills.core[:10]
                exp_lines = []
                for exp in prof.work_experience[:3]:
                    role_title = exp.get("title") or exp.get("titleDe") or ""
                    comp = exp.get("company", "")
                    desc = exp.get("descriptionDe" if lang.lower().startswith("de") else "descriptionEn") or exp.get("descriptionEn") or ""
                    if role_title and comp:
                        exp_lines.append(f"  * {role_title} at {comp}: {desc[:180]}")
                exp_summary = "\n".join(exp_lines) if exp_lines else "Experienced Software Engineer"

                profile_context = (
                    f"- Candidate: {cand_name}\n"
                    f"- Summary: {pers.summaryDe or pers.summaryEn or 'Experienced Senior Software Engineer'}\n"
                    f"- Core Skills: {', '.join(skills_list)}\n"
                    f"- Recent Experience:\n{exp_summary}\n"
                    f"- Location: {pers.city or pers.address}\n"
                )

                if contact_person:
                    salutation = f"Sehr geehrte(r) {contact_person}," if lang.lower().startswith("de") else f"Dear {contact_person},"
                else:
                    salutation = "Sehr geehrte Damen und Herren," if lang.lower().startswith("de") else "Dear Hiring Team,"

                prompt_template = self._load_template_file(f"cover_letter_prompt_{'de' if lang.lower().startswith('de') else 'en'}.txt")
                prompt = prompt_template.format(
                    cand_name=cand_name,
                    headline="Senior Software Engineer",
                    role_display=role_display,
                    comp_display=comp_display,
                    profile_context=profile_context,
                    salutation=salutation,
                )

                llm_response = call_gemini_semantic_analysis(prompt)
                if llm_response and len(llm_response.strip()) > 100:
                    body_text = llm_response.strip()
            except Exception as e:
                log.warning("Gemini cover letter generation failed, using clean template fallback: %s", e)

        if not body_text:
            raw_tmpl = self._load_template_file(f"cover_letter_default.{'de' if lang.lower().startswith('de') else 'en'}.txt")
            body_text = (
                raw_tmpl
                .replace("{job_title}", role_display)
                .replace("{company}", comp_display)
                .replace("{candidate_name}", cand_name)
            )

        # Convert text paragraphs into HTML, stripping any trailing signature duplicates
        paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
        closing_patterns = ["mit freundlichen grüßen", "sincerely", "best regards", "kind regards", "hochachtungsvoll"]
        filtered_paragraphs = []
        for p in paragraphs:
            p_clean = p.lower().strip()
            if any(p_clean.startswith(cl) for cl in closing_patterns):
                continue
            if p.strip() == cand_name.strip():
                continue
            filtered_paragraphs.append(p)
        body_html = "\n".join(f"    <p>{p.replace(chr(10), '<br>')}</p>" for p in filtered_paragraphs)

        # 4. Render HTML template
        html_template = self._load_template_file("cover_letter_template.html")
        closing = "Mit freundlichen Grüßen," if lang.lower().startswith("de") else "Sincerely,"
        subject = f"Bewerbung als {role_display}" if lang.lower().startswith("de") else f"Application for {role_display}"

        rendered_html = (
            html_template
            .replace("{{ LANG }}", "de" if lang.lower().startswith("de") else "en")
            .replace("{{ SENDER_NAME }}", cand_name)
            .replace("{{ SENDER_CONTACT }}", contact_line)
            .replace("{{ RECIPIENT }}", recipient_display.replace("\n", "<br>"))
            .replace("{{ DATE }}", formatted_date)
            .replace("{{ SUBJECT }}", subject)
            .replace("{{ BODY }}", body_html)
            .replace("{{ CLOSING }}", closing)
        )

        html_path.write_text(rendered_html, encoding="utf-8")
        log.info("Cover letter HTML rendered: %s", html_path)

        # 5. Compile PDF via Playwright
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(html_path.as_uri())
                page.pdf(path=str(pdf_path), format="A4", print_background=True)
                browser.close()
            log.info("Cover letter PDF compiled successfully: %s", pdf_path)
        except Exception as e:
            log.warning("Playwright PDF generation failed: %s. HTML remains available at %s", e, html_path)

        # 6. Update profile.local.json with new cover letter path
        self._update_profile_cover_letter(str(pdf_path), comp_display, role_display)

        return {
            "pdf_path": str(pdf_path) if pdf_path.exists() else str(html_path),
            "html_path": str(html_path),
            "filename": pdf_path.name if pdf_path.exists() else html_path.name,
            "company": comp_display,
            "role": role_display,
            "language": lang,
            "generated_at": now.isoformat(),
        }

    def _update_profile_cover_letter(self, pdf_path: str, company: str, role: str) -> None:
        """Updates documents.coverLetter in profile.local.json."""
        root_dir = Path(__file__).resolve().parent.parent.parent
        p_path = root_dir / "profile.local.json"
        if not p_path.exists():
            return
        try:
            with open(p_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            docs = data.setdefault("documents", {})
            docs["coverLetter"] = pdf_path
            docs["coverLetterCompany"] = company
            docs["coverLetterRole"] = role
            with open(p_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log.info("Updated profile.local.json with latest cover letter: %s", pdf_path)
        except Exception as e:
            log.warning("Could not update profile.local.json cover letter path: %s", e)
