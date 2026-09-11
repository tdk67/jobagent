"""Captures full-page visual PDF snapshots of job postings via Playwright."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from playwright.sync_api import sync_playwright

from src.tools.archive.url_guard import is_safe_url


class JobSnapshotter:
    """Headless browser snapshotter for visual PDF preservation."""

    def __init__(self, output_dir: str = "data/snapshots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def capture_from_url(
        self,
        url: str,
        output_filename: str,
        timeout_ms: int = 30000,
    ) -> str:
        """Navigates to URL and captures a high-resolution full-page PDF snapshot."""
        cleaned_url = url.strip()
        if not (cleaned_url.lower().startswith("http://") or cleaned_url.lower().startswith("https://")):
            raise ValueError(f"Security restriction: Only HTTP/HTTPS URLs are allowed for snapshotting, got: {url}")
        if not is_safe_url(cleaned_url):
            raise ValueError(f"Security restriction: URL rejected by SSRF guard: {url}")

        out_file = self.output_dir / output_filename
        out_file.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # SSRF TOCTOU guard (P4): intercept all subresources and redirects to verify safe destinations
            def _ssrf_route_interceptor(route):
                req_url = route.request.url.lower()
                if req_url.startswith("data:") or req_url.startswith("blob:"):
                    route.continue_()
                    return
                if not is_safe_url(route.request.url):
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            page.route("**/*", _ssrf_route_interceptor)
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                # Fallback to load state if networkidle times out
                page.goto(url, wait_until="load", timeout=timeout_ms)

            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()

        with open(out_file, "wb") as f:
            f.write(pdf_bytes)

        return str(out_file.resolve())

    def capture_from_html(
        self,
        html_content: str,
        output_filename: str,
    ) -> str:
        """Renders raw HTML content and saves it as a PDF snapshot."""
        out_file = self.output_dir / output_filename
        out_file.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content, wait_until="load")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()

        with open(out_file, "wb") as f:
            f.write(pdf_bytes)

        return str(out_file.resolve())
