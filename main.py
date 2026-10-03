"""
Morning Gazette Pipeline - Main Orchestrator & CLI Entry Point.

Coordinates data ingestion across tech, AI, and financial APIs,
invokes Google Gemini for structured editorial synthesis,
renders a newspaper layout with inlined CSS,
and produces a local preview or dispatches via SMTP.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from builders.email_builder import EmailBuilder
from config import get_settings, setup_logging
from fetchers import collect_all_data
from processors.summarizer import GeminiSummarizer

logger = logging.getLogger("morning_gazette.main")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="The Morning Gazette - Automated AI-Powered Daily Newspaper Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Generate local preview.html without sending email (default behavior).",
    )
    parser.add_argument(
        "--force-send",
        action="store_true",
        help="Force email transmission via SMTP regardless of dry-run default.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Custom destination path for preview HTML (default: dist/preview.html).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override logging verbosity level.",
    )

    return parser.parse_args()


async def run_pipeline(dry_run: bool = True, output_path: Path | None = None) -> int:
    """
    Execute the end-to-end Morning Gazette pipeline.

    Returns:
        0 on success, non-zero on critical failure.
    """
    settings = get_settings()

    logger.info("=" * 65)
    logger.info("  STARTING THE MORNING GAZETTE PIPELINE")
    logger.info("=" * 65)

    # 1. Asynchronous Parallel Data Collection
    logger.info("[Step 1/4] Ingesting data from tech, AI, and finance sources...")
    raw_data = await collect_all_data(timeout=settings.REQUEST_TIMEOUT)

    # 2. Structured AI Editorial Processing
    logger.info("[Step 2/4] Synthesizing editorial content with Gemini (or Fallback)...")
    summarizer = GeminiSummarizer(settings=settings)
    gazette_content = await summarizer.summarize(raw_data)

    logger.info("Editorial synthesis complete:")
    logger.info("  - Manşet: %s", gazette_content.headline.title)
    logger.info("  - Girişim & Teknoloji Haberleri: %d adet", len(gazette_content.tech_startup_stories))
    logger.info("  - Yeni AI Araçları & Modeller: %d adet", len(gazette_content.ai_tools))

    # 3. Design & HTML Assembly
    logger.info("[Step 3/4] Rendering newspaper layout and inlining CSS...")
    builder = EmailBuilder(settings=settings)
    final_html = builder.build_html(gazette_content)
    size_bytes = len(final_html.encode("utf-8"))

    # 4. Delivery / Dry-Run Output
    logger.info("[Step 4/4] Finalizing delivery...")
    preview_file = builder.save_preview(final_html, output_path=output_path)
    logger.info("Preview HTML generated at: %s (Size: %.2f KB)", preview_file.resolve(), size_bytes / 1024)

    if not dry_run:
        logger.info("Dispatching email via SMTP...")
        success = builder.send_email(final_html, gazette_content)
        if not success:
            logger.error("Email dispatch failed. Please verify SMTP configuration.")
            return 1
        logger.info("Morning Gazette successfully sent to recipients!")
    else:
        logger.info("[DRY-RUN ACTIVE] Email dispatch skipped. View preview at: %s", preview_file.resolve())

    logger.info("=" * 65)
    logger.info("  PIPELINE EXECUTION COMPLETED SUCCESSFULLY")
    logger.info("=" * 65)
    return 0


def main() -> None:
    """CLI Entry point."""
    args = parse_arguments()
    settings = get_settings()

    log_level = args.log_level or settings.LOG_LEVEL
    setup_logging(log_level)

    is_dry_run = not args.force_send if args.force_send else True

    try:
        exit_code = asyncio.run(run_pipeline(dry_run=is_dry_run, output_path=args.output))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Pipeline execution interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        logger.critical("Fatal pipeline error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
