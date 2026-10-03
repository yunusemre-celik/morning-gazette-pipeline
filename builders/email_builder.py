"""
Email Builder Module.

Renders GazetteContent via Jinja2 into templates/newspaper.html,
inlines all CSS styles using premailer, validates the < 85 KB size constraint,
and provides standard SSL/TLS SMTP dispatch functionality.
"""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
from pathlib import Path
import re
import smtplib
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
import premailer
import cssutils

from config import Settings, get_settings

# Suppress harmless vendor CSS warnings from cssutils
cssutils.log.setLevel(logging.CRITICAL)

logger = logging.getLogger("builders.email_builder")

MAX_EMAIL_SIZE_BYTES = 85 * 1024  # 85 KB threshold to prevent Gmail clipping (102 KB)


class EmailBuilder:
    """Renders, inlines, and dispatches the Morning Gazette newsletter."""

    def __init__(self, template_dir: Optional[Path] = None, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.template_dir = template_dir or (Path(__file__).parent.parent / "templates")

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_raw_html(self, content: GazetteContent) -> str:
        """Render the Jinja2 template with the given content."""
        template = self.jinja_env.get_template("newspaper.html")
        return template.render(content=content)

    def inline_css(self, raw_html: str) -> str:
        """Inline CSS styles using premailer to ensure maximum email client compatibility."""
        p = premailer.Premailer(
            html=raw_html,
            keep_style_tags=False,
            strip_important=False,
            align_floating_images=False,
            remove_unset_properties=True,
        )
        return p.transform()

    @staticmethod
    def _minify_whitespace(html_str: str) -> str:
        """Clean redundant whitespace between HTML tags."""
        # Replace multiple spaces and newlines between tags with single newline
        cleaned = re.sub(r">\s+<", "><", html_str)
        return cleaned.strip()

    def build_html(self, content: GazetteContent) -> str:
        """
        Produce production-ready, CSS-inlined, size-validated HTML.

        Enforces strictly that the final size is below 85 KB.
        """
        raw_html = self.render_raw_html(content)
        inlined_html = self.inline_css(raw_html)

        html_bytes = inlined_html.encode("utf-8")
        current_size = len(html_bytes)

        logger.info("Rendered inlined HTML size: %d bytes (%.2f KB).", current_size, current_size / 1024)

        if current_size > MAX_EMAIL_SIZE_BYTES:
            logger.warning(
                "HTML size (%d bytes) exceeds 85 KB limit (%d bytes). Applying minification...",
                current_size,
                MAX_EMAIL_SIZE_BYTES,
            )
            minified_html = self._minify_whitespace(inlined_html)
            minified_bytes = minified_html.encode("utf-8")
            current_size = len(minified_bytes)
            logger.info("Minified HTML size: %d bytes (%.2f KB).", current_size, current_size / 1024)

            if current_size > MAX_EMAIL_SIZE_BYTES:
                raise ValueError(
                    f"Final email HTML size ({current_size} bytes) exceeds strict 85 KB limit ({MAX_EMAIL_SIZE_BYTES} bytes)."
                )
            return minified_html

        return inlined_html

    def save_preview(self, html_content: str, output_path: Optional[Path] = None) -> Path:
        """Save HTML to dist/preview.html for dry-run verification."""
        target_path = output_path or (self.settings.DIST_DIR / "preview.html")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        target_path.write_text(html_content, encoding="utf-8")
        logger.info("Preview successfully saved to: %s (%d bytes)", target_path.resolve(), len(html_content.encode("utf-8")))
        return target_path

    def send_email(self, html_content: str, content: GazetteContent) -> bool:
        """
        Dispatch newsletter via standard SMTP with SSL/TLS.

        Strictly avoids Gmail API or OAuth2.
        """
        cfg = self.settings
        if not cfg.SMTP_HOST or not cfg.SMTP_USER or not cfg.SMTP_PASSWORD:
            logger.error("SMTP credentials not configured. Email dispatch aborted.")
            return False

        if not cfg.RECIPIENT_EMAILS:
            logger.error("No recipient emails configured.")
            return False

        subject = f"The Morning Gazette — {content.edition_date} — {content.headline.title[:60]}"
        logger.info("Preparing SMTP dispatch to %d recipients via %s:%d...", len(cfg.RECIPIENT_EMAILS), cfg.SMTP_HOST, cfg.SMTP_PORT)

        # Plain-text alternative
        plain_text = (
            f"THE MORNING GAZETTE — {content.edition_date}\n\n"
            f"MANŞET: {content.headline.title}\n"
            f"{content.headline.lead_paragraph}\n\n"
            f"Haberin devamı: {content.headline.source_url}\n\n"
            f"PİYASA NOTU:\n"
            f"{content.market_insight.market_summary}\n"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.SENDER_EMAIL
        msg["To"] = ", ".join(cfg.RECIPIENT_EMAILS)

        part_text = MIMEText(plain_text, "plain", "utf-8")
        part_html = MIMEText(html_content, "html", "utf-8")

        msg.attach(part_text)
        msg.attach(part_html)

        try:
            if cfg.SMTP_USE_SSL:
                with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=15) as server:
                    server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
                    server.sendmail(cfg.SENDER_EMAIL, cfg.RECIPIENT_EMAILS, msg.as_string())
            else:
                with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=15) as server:
                    if cfg.SMTP_USE_TLS:
                        server.starttls()
                    server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
                    server.sendmail(cfg.SENDER_EMAIL, cfg.RECIPIENT_EMAILS, msg.as_string())

            logger.info("Successfully dispatched Morning Gazette to %d recipients.", len(cfg.RECIPIENT_EMAILS))
            return True
        except Exception as exc:
            logger.error("Failed to send email via SMTP: %s", exc, exc_info=True)
            return False
