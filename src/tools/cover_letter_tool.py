"""Cover Letter Generator Engine (DIN 5008 Standard).

Adheres to clean-code-architecture:
- Templates strictly separated into templates/cover_letter/ (never hardcoded in Python).
- Candidate PII loaded strictly from profile.local.json.
- Tailored engineer-to-engineer tone (anti-AI-slop) with Gemini Flash semantic reasoning.
- High-fidelity PDF rendering via Playwright.
"""

from __future__ import annotations

import html
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


class CoverLetterGenerationError(RuntimeError):
    """Raised when cover letter text generation fails due to missing credentials, rate limits, or API errors."""
    pass


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
        body_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates DIN 5008 HTML and PDF cover letters tailored to the target role.

        Raises:
            CoverLetterGenerationError: When AI generation fails and no explicit body_text was provided.

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

        # 3. Determine body content (explicit body_text or Gemini reasoning)
        if not body_text:
            if not use_gemini:
                raise CoverLetterGenerationError(
                    "Cover letter generation requires AI reasoning (use_gemini=True) or explicit body_text. "
                    "Generic static fallbacks are disabled to ensure all applications are tailored to the role and candidate CV."
                )

            key = os.getenv("GEMINI_API_KEY")
            if not key:
                raise CoverLetterGenerationError(
                    "GEMINI_API_KEY is not configured in environment (.env). "
                    "AI cover letter generation requires a valid Gemini API key to tailor content to candidate CV achievements and job description."
                )

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

                llm_response = call_gemini_semantic_analysis(prompt, raise_on_error=True)
                if not llm_response or len(llm_response.strip()) < 80:
                    raise CoverLetterGenerationError(
                        "Gemini returned an empty or insufficient response (<80 chars). "
                        "Please verify model configuration or prompt inputs."
                    )
                body_text = llm_response.strip()

            except CoverLetterGenerationError:
                raise
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    raise CoverLetterGenerationError(
                        f"Gemini API quota exceeded or rate-limited (HTTP 429). "
                        f"Please check your account quota or wait before retrying. Details: {e}"
                    ) from e
                if "api_key" in err_str or "permission" in err_str or "unauthenticated" in err_str:
                    raise CoverLetterGenerationError(
                        f"Gemini API key is invalid or unauthorized: {e}"
                    ) from e
                raise CoverLetterGenerationError(
                    f"Gemini cover letter generation failed: {e}"
                ) from e

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
        body_html = "\n".join(f"    <p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in filtered_paragraphs)

        # 4. Render HTML template
        html_template = self._load_template_file("cover_letter_template.html")
        closing = "Mit freundlichen Grüßen," if lang.lower().startswith("de") else "Sincerely,"
        raw_subject = f"Bewerbung als {role_display}" if lang.lower().startswith("de") else f"Application for {role_display}"

        rendered_html = (
            html_template
            .replace("{{ LANG }}", "de" if lang.lower().startswith("de") else "en")
            .replace("{{ SENDER_NAME }}", html.escape(cand_name))
            .replace("{{ SENDER_CONTACT }}", html.escape(contact_line))
            .replace("{{ RECIPIENT }}", html.escape(recipient_display).replace("\n", "<br>"))
            .replace("{{ DATE }}", html.escape(formatted_date))
            .replace("{{ SUBJECT }}", html.escape(raw_subject))
            .replace("{{ BODY }}", body_html)
            .replace("{{ CLOSING }}", html.escape(closing))
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
