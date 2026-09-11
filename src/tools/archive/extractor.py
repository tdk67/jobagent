"""Cleans job posting DOM/HTML and converts it to structured Markdown."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import markdownify


class JobContentExtractor:
    """Extracts readable markdown and metadata from raw HTML postings."""

    BOILERPLATE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe", "svg"]
    COOKIE_CLASSES = [
        "cookie", "consent", "banner", "gdpr", "overlay", "modal", "advertisement", "tracking"
    ]

    def clean_html(self, html_content: str) -> str:
        """Removes scripts, cookie banners, navigation menus, and non-content elements."""
        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(self.BOILERPLATE_TAGS):
            tag.decompose()

        # Remove elements with cookie/gdpr classes
        for tag in soup.find_all(True):
            cls_list = tag.get("class", [])
            if isinstance(cls_list, list):
                classes = " ".join(cls_list).lower()
                if any(c in classes for c in self.COOKIE_CLASSES):
                    tag.decompose()

        return str(soup)

    def to_markdown(self, html_content: str, title: str = "", company: str = "") -> str:
        """Converts cleaned HTML to clean Markdown with metadata headers."""
        cleaned = self.clean_html(html_content)
        md = markdownify.markdownify(cleaned, heading_style="ATX", strip=["img"])

        # Collapse excess empty lines
        lines = [line.rstrip() for line in md.splitlines()]
        condensed: List[str] = []
        prev_blank = False
        for line in lines:
            if not line.strip():
                if not prev_blank:
                    condensed.append("")
                prev_blank = True
            else:
                condensed.append(line)
                prev_blank = False

        body_md = "\n".join(condensed).strip()

        # Add clean header
        header = f"# {title or 'Job Posting'}\n"
        if company:
            header += f"**Company:** {company}\n"
        header += "---\n\n"

        return header + body_md

    def extract_metadata(self, text: str) -> Dict[str, Any]:
        """Extracts salary indicators and work location from text."""
        meta: Dict[str, Any] = {
            "salary": None,
            "location": None,
            "work_model": None,
        }

        # Match EUR/USD salary ranges (e.g. 70.000 - 90.000 EUR or $120k-$150k)
        salary_match = re.search(
            r"(?:€|\$|EUR|USD)?\s*\d{2,3}(?:[.,]\d{3})*(?:\s*(?:-|bis|to)\s*\d{2,3}(?:[.,]\d{3})*)?\s*(?:€|\$|EUR|USD|k|K)?\s*(?:(?:pro|per|/)\s*(?:Jahr|year|Monat|month|annum))?",
            text,
            flags=re.IGNORECASE,
        )
        if salary_match and any(c.isdigit() for c in salary_match.group(0)):
            matched = salary_match.group(0).strip()
            if len(matched) >= 4:
                meta["salary"] = matched

        # Match work model
        if re.search(r"\bremote\b", text, flags=re.IGNORECASE):
            meta["work_model"] = "Remote"
        elif re.search(r"\bhybrid\b", text, flags=re.IGNORECASE):
            meta["work_model"] = "Hybrid"
        elif re.search(r"\bon-site\b|\bvor ort\b", text, flags=re.IGNORECASE):
            meta["work_model"] = "On-site"

        return meta
