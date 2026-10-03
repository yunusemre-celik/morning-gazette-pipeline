"""
Unit and Mock Tests for Email Builder, Jinja2 Template, and SMTP Dispatch.

Tests template rendering, premailer CSS inlining, strict 85 KB size constraints,
preview generation, and standard SMTP dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from builders.email_builder import EmailBuilder, MAX_EMAIL_SIZE_BYTES
from config import Settings
from fetchers.base import CryptoPrice, FinanceSummary, FXRate
from processors.schema import (
    AIToolModel,
    GazetteContent,
    HeadlineStory,
    MarketInsight,
    TechStartupArticle,
)


@pytest.fixture
def sample_gazette_content() -> GazetteContent:
    """Fixture providing a complete GazetteContent instance."""
    headline = HeadlineStory(
        kicker="MANŞET HABER",
        title="Yeni Nesil Otonom Pipeline Mimarisi Hayata Geçti",
        lead_paragraph="Geliştirici ekibi modern gazete mizanpajında e-posta bülteni üreten boru hattını tamamladı.",
        detailed_analysis="Açık kaynak API'ler, asenkron veri toplama ve Gemini 2.5 Flash ile entegre edilen sistem kusursuz çalışıyor.",
        source_name="The Morning Gazette",
        source_url="https://github.com/morning-gazette",
    )

    stories = [
        TechStartupArticle(
            category="YAZILIM",
            title=f"Teknoloji Gelişmesi #{i}",
            summary="Yazılım mimarilerinde yeni standartlar belirleniyor.",
            key_takeaway="Sistem güvenilirliği ve esnekliği artırıldı.",
            source_name="Hacker News",
            source_url="https://news.ycombinator.com",
        )
        for i in range(1, 5)
    ]

    tools = [
        AIToolModel(
            name=f"AI-Model-{i}",
            category="Açık Kaynak Model",
            description="Verimli dil modelleme kütüphanesi.",
            why_it_matters="Geliştiricilerin yerel test süreçlerini 5 kat hızlandırıyor.",
            source_url="https://huggingface.co/sample",
        )
        for i in range(1, 4)
    ]

    market = MarketInsight(
        market_summary="Küresel piyasalar olumlu bir eğilimle günü karşılıyor.",
        fx_commentary="Dolar/TL 49.00 TL seviyelerinde.",
        crypto_commentary="Bitcoin 86.000$ bandında güçlü seyrini sürdürüyor.",
        editorial_take="Erken aşama girişimler için nakit akışı stratejileri optimize edilmeli.",
    )

    finance = FinanceSummary(
        fx_rates=[
            FXRate(base_currency="USD", target_currency="TRY", rate=49.10),
            FXRate(base_currency="EUR", target_currency="TRY", rate=55.40),
        ],
        crypto_prices=[
            CryptoPrice(symbol="BTC", name="Bitcoin", price_usd=86400.0, change_24h=3.2),
            CryptoPrice(symbol="ETH", name="Ethereum", price_usd=2750.0, change_24h=-0.8),
        ],
    )

    return GazetteContent(
        edition_date="2 Ekim 2026, Cuma",
        edition_number="No. 26275",
        headline=headline,
        tech_startup_stories=stories,
        ai_tools=tools,
        market_insight=market,
        raw_finance=finance,
    )


# ------------------------------------------------------------------------------
# 1. Template Rendering & Inlining Tests
# ------------------------------------------------------------------------------

def test_template_rendering_and_inlining(sample_gazette_content: GazetteContent):
    """Verify HTML renders and styles are correctly inlined."""
    builder = EmailBuilder()
    html_output = builder.build_html(sample_gazette_content)

    assert "<html" in html_output
    assert "The Morning Gazette" in html_output
    assert sample_gazette_content.headline.title in html_output

    # Verify CSS inlining: style attributes must be present on elements
    assert "style=" in html_output
    assert "background-color" in html_output


def test_html_size_under_85kb(sample_gazette_content: GazetteContent):
    """Enforce strict constraint: Final HTML size must be < 85 KB to prevent Gmail clipping."""
    builder = EmailBuilder()
    html_output = builder.build_html(sample_gazette_content)

    size_in_bytes = len(html_output.encode("utf-8"))
    assert size_in_bytes < MAX_EMAIL_SIZE_BYTES, f"HTML size ({size_in_bytes} bytes) exceeded 85 KB limit ({MAX_EMAIL_SIZE_BYTES} bytes)"


def test_preview_saving(tmp_path: Path, sample_gazette_content: GazetteContent):
    """Test saving preview.html to custom directory."""
    builder = EmailBuilder()
    html_output = builder.build_html(sample_gazette_content)

    dest = tmp_path / "custom_dist" / "preview.html"
    saved_path = builder.save_preview(html_output, output_path=dest)

    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == html_output


# ------------------------------------------------------------------------------
# 2. SMTP Sending Tests (Mocked)
# ------------------------------------------------------------------------------

def test_send_email_aborts_without_smtp_credentials(sample_gazette_content: GazetteContent):
    """Verify send_email gracefully returns False when SMTP is unconfigured."""
    settings = Settings(SMTP_HOST="", SMTP_USER="", SMTP_PASSWORD="")
    builder = EmailBuilder(settings=settings)

    success = builder.send_email("<html></html>", sample_gazette_content)
    assert success is False


def test_send_email_tls_success_mock(sample_gazette_content: GazetteContent):
    """Verify STARTTLS SMTP dispatch."""
    settings = Settings(
        SMTP_HOST="smtp.mailgun.org",
        SMTP_PORT=587,
        SMTP_USER="test_user",
        SMTP_PASSWORD="test_password",
        SMTP_USE_TLS=True,
        SMTP_USE_SSL=False,
        SENDER_EMAIL="editor@morninggazette.internal",
        RECIPIENT_EMAILS=["reader@example.com"],
    )
    builder = EmailBuilder(settings=settings)

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = builder.send_email("<html><body>Newsletter</body></html>", sample_gazette_content)

        assert success is True
        mock_smtp_cls.assert_called_once_with("smtp.mailgun.org", 587, timeout=15)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test_user", "test_password")
        mock_server.sendmail.assert_called_once()


def test_send_email_ssl_success_mock(sample_gazette_content: GazetteContent):
    """Verify SSL SMTP dispatch."""
    settings = Settings(
        SMTP_HOST="smtp.sendgrid.net",
        SMTP_PORT=465,
        SMTP_USER="apikey",
        SMTP_PASSWORD="secret_password",
        SMTP_USE_TLS=False,
        SMTP_USE_SSL=True,
        SENDER_EMAIL="editor@morninggazette.internal",
        RECIPIENT_EMAILS=["reader@example.com"],
    )
    builder = EmailBuilder(settings=settings)

    with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
        mock_server = MagicMock()
        mock_ssl_cls.return_value.__enter__.return_value = mock_server

        success = builder.send_email("<html><body>Newsletter</body></html>", sample_gazette_content)

        assert success is True
        mock_ssl_cls.assert_called_once_with("smtp.sendgrid.net", 465, timeout=15)
        mock_server.login.assert_called_once_with("apikey", "secret_password")
        mock_server.sendmail.assert_called_once()
