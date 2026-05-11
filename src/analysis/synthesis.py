"""LLM synthesis stub — placeholder for the final "Should I buy this?" section.

The actual LLM call will be wired up later. This module provides a
fallback summary so the pipeline doesn't break without an LLM.
"""

from __future__ import annotations

from src.config import Config
from src.models.report import Report


def generate_synthesis(report: Report, config: Config) -> str:
    """Generate a synthesis summary string for the report.

    Currently a stub that produces a simple description. The actual
    LLM integration will be added in a future update.

    Args:
        report: The fully populated Report object.
        config: Application Config (reserved for future LLM settings).

    Returns:
        A summary string suitable for the report's synthesis section.
    """
    primary = report.primary_product

    if primary is None:
        return "No product data available for synthesis."

    review_count = 0
    avg_rating = 0.0
    if report.review_summary:
        review_count = report.review_summary.total_reviews
        avg_rating = report.review_summary.avg_rating

    parts = [
        f"Based on {review_count} reviews",
        f"with an average rating of {avg_rating:.1f} stars",
    ]

    # Add trend info if available
    if report.temporal:
        parts.append(
            f"and a {report.temporal.trend_direction} recent trend"
        )

    # Add fake review risk if available
    if report.fake_signals:
        parts.append(
            f"(fake review risk: {report.fake_signals.overall_risk})"
        )

    parts.append(".")

    return " ".join(parts)
