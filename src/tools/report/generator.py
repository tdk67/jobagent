"""HTML and PDF report generator utilizing Jinja2 and Playwright."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright


class ReportGenerator:
    """Renders structured Jinja2 templates and compiles them to PDF."""

    VIEW_TEMPLATES = {
        "dashboard": "dashboard.html",
        "afa_table": "afa_proof_table.html",
        "agency_summary": "agency_summary.html",
    }

    def __init__(self, template_dir: str = "templates", output_dir: str = "output"):
        self.template_dir = Path(template_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_html(self, view_type: str, data: Dict[str, Any]) -> str:
        """Renders view into an HTML document."""
        template_name = self.VIEW_TEMPLATES.get(view_type, "dashboard.html")
        template = self.jinja_env.get_template(template_name)
        rendered = template.render(**data)

        out_path = self.output_dir / f"{view_type}_report.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered)

        return str(out_path.resolve())

    def convert_html_to_pdf(
        self,
        html_file_path: str,
        output_pdf_name: str,
        landscape: bool = False,
    ) -> str:
        """Compiles HTML into a print-ready PDF using Playwright headless Chromium."""
        out_pdf = self.output_dir / output_pdf_name
        file_url = Path(html_file_path).resolve().as_uri()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(file_url, wait_until="load")
            pdf_bytes = page.pdf(
                format="A4",
                landscape=landscape,
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"},
            )
            browser.close()

        try:
            with open(out_pdf, "wb") as f:
                f.write(pdf_bytes)
            target = out_pdf
        except PermissionError:
            fallback = self.output_dir / f"{out_pdf.stem}_new.pdf"
            with open(fallback, "wb") as f:
                f.write(pdf_bytes)
            target = fallback

        return str(target.resolve())
