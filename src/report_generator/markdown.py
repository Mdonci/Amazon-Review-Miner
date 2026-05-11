"""Markdown report generator for Amazon Review Miner.

Generates a rich, emoji-laden GitHub-flavored markdown report from a Report
dataclass, following the template specified in CODER_BRIEF.md.
"""

from __future__ import annotations

import os
from datetime import datetime

from src.models.report import (
    ComparedProduct,
    CompetitiveComparison,
    FakeReviewSignals,
    MonthlyBucket,
    Report,
    ReviewSummary,
    TemporalTrend,
)


# ---------------------------------------------------------------------------
# Emoji / visual helpers
# ---------------------------------------------------------------------------

_TREND_ARROW: dict[str, str] = {
    "improving": "↑",
    "declining": "↓",
    "stable": "→",
    "mixed": "↑↓",
}

_RISK_EMOJI: dict[str, str] = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
}


def _trend_arrow(direction: str | None) -> str:
    d = (direction or "").strip().lower()
    return _TREND_ARROW.get(d, "→")


def _risk_cell(risk: str | None) -> str:
    r = (risk or "low").strip().lower()
    return f"{_RISK_EMOJI.get(r, '🟢')} {r.title()}"


def _risk_emoji(risk: str | None) -> str:
    r = (risk or "low").strip().lower()
    return _RISK_EMOJI.get(r, "🟢")


def _stars(rating: float | None) -> str:
    if rating is None:
        return "⭐ N/A"
    return f"⭐ {rating:.1f}"


# ---------------------------------------------------------------------------
# Section builders — each returns a list[str] of markdown lines
# ---------------------------------------------------------------------------


def _header(report: Report) -> list[str]:
    product = report.primary_product
    title = product.title if product else "Unknown Product"
    gen_date = report.generated_at.strftime("%B %d, %Y")
    return [
        f"# Amazon Review Report: {title}",
        "",
        f"**Generated:** {gen_date} | **Query:** {report.query}",
        "",
        "---",
    ]


def _verdict(report: Report) -> list[str]:
    lines = ["## 🏆 Verdict", ""]
    if report.synthesis:
        lines.append(report.synthesis)
    else:
        lines.append("*No synthesis available.*")
    return lines + ["", "---"]


def _quick_stats(report: Report) -> list[str]:
    product = report.primary_product
    summary = report.review_summary
    temporal = report.temporal
    fake = report.fake_signals

    price = f"${product.price:.2f}" if product and product.price is not None else "N/A"

    if summary:
        rating = f"⭐ {summary.avg_rating:.1f} ({summary.total_reviews} reviews)"
    else:
        rating = "N/A"

    # Recent 30d trend
    if temporal:
        arrow = _trend_arrow(temporal.trend_direction)
        label = temporal.trend_direction.title()
        recent = f"{arrow} {label}"
    else:
        recent = "N/A"

    # Fake risk
    if fake:
        fake_text = _risk_cell(fake.overall_risk)
    else:
        fake_text = "N/A"

    bsr = product.bs_rank if product and product.bs_rank else "N/A"
    if bsr != "N/A":
        bsr = f"#{bsr}"

    return [
        "## 📊 Quick Stats",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Price | {price} |",
        f"| Avg Rating | {rating} |",
        f"| Recent 30d Trend | {recent} |",
        f"| Fake Review Risk | {fake_text} |",
        f"| BSR | {bsr} |",
        "",
        "---",
    ]


def _rating_over_time(report: Report) -> list[str]:
    temporal = report.temporal
    lines = ["## 📈 Rating Over Time", ""]

    if not temporal or not temporal.monthly_data:
        lines.append("*No temporal data available.*")
        return lines + ["", "---"]

    lines.append(
        "| Month | Avg Rating | Reviews | Trend |"
    )
    lines.append("|---|---|---|---|")

    prev_avg: float | None = None
    for bucket in temporal.monthly_data:
        if prev_avg is None:
            arrow = ""
        elif bucket.avg_rating > prev_avg:
            arrow = " ↑"
        elif bucket.avg_rating < prev_avg:
            arrow = " ↓"
        else:
            arrow = " →"

        lines.append(
            f"| {bucket.year_month} "
            f"| ⭐ {bucket.avg_rating:.2f} "
            f"| {bucket.review_count} "
            f"| {arrow} |"
        )
        prev_avg = bucket.avg_rating

    # Anomaly call-out
    if temporal.anomaly_months:
        lines.append("")
        lines.append(
            "⚠️ **Anomaly months:** "
            + ", ".join(temporal.anomaly_months)
        )

    return lines + ["", "---"]


def _pros_cons(report: Report) -> list[str]:
    lines = ["## 👍 Pros & 👎 Cons", ""]

    # ---------- Pros ----------
    lines.append("### What People Love")
    if report.pros:
        breakdown = report.sentiment_breakdown
        # Try to pull frequency info from sentiment_breakdown
        pros_freq: dict[str, float | int] = {}
        if isinstance(breakdown, dict):
            pros_freq = breakdown.get("pros_frequencies", {}) or {}

        for i, pro in enumerate(report.pros, 1):
            freq = _get_freq(pro, pros_freq)
            suffix = f" — mentioned in {freq}% of reviews" if freq is not None else ""
            lines.append(f"{i}. {pro}{suffix}")
    else:
        lines.append("*No pros extracted.*")

    lines.append("")

    # ---------- Cons ----------
    lines.append("### What People Complain About")
    if report.cons:
        cons_freq: dict[str, float | int] = {}
        if isinstance(report.sentiment_breakdown, dict):
            cons_freq = report.sentiment_breakdown.get("cons_frequencies", {}) or {}

        for i, con in enumerate(report.cons, 1):
            freq = _get_freq(con, cons_freq)
            suffix = f" — mentioned in {freq}% of reviews" if freq is not None else ""
            lines.append(f"{i}. {con}{suffix}")
    else:
        lines.append("*No cons extracted.*")

    return lines + ["", "---"]


def _get_freq(item: str, freq_map: dict) -> float | int | None:
    """Try to find a frequency for *item* in *freq_map*."""
    # Direct key match
    if item in freq_map:
        return freq_map[item]
    # Case-insensitive
    item_lower = item.strip().lower()
    for k, v in freq_map.items():
        if k.strip().lower() == item_lower:
            return v
    return None


def _fake_review_analysis(report: Report) -> list[str]:
    fake = report.fake_signals
    lines = ["## 🔍 Fake Review Analysis", ""]

    if not fake:
        lines.append("*No fake-review analysis available.*")
        return lines + ["", "---"]

    lines.append(f"- **{fake.vine_percentage:.1f}%** Vine Voice reviews")
    lines.append(f"- **{fake.unverified_percentage:.1f}%** unverified purchases")
    lines.append(
        f"- Burst rate: **{fake.burst_rate:.1f}** reviews/day "
        f"(max in any 7-day window)"
    )
    lines.append(
        f"- Average reviewer depth: **{fake.avg_reviewer_depth:.1f}** "
        f"total reviews per reviewer"
    )
    lines.append(
        f"- **{fake.one_review_account_pct:.1f}%** of reviewers have only 1 review"
    )
    lines.append(
        f"- Template-like text detected in **{fake.template_text_pct:.1f}%** "
        f"of reviews"
    )

    if fake.suspicious_timing:
        lines.append(
            "- ⚠️ **Suspicious timing** — burst activity with low reviewer depth"
        )

    lines.append("")
    lines.append(
        f"### Risk Assessment: {_risk_cell(fake.overall_risk)} "
        f"(score: {fake.risk_score:.2f})"
    )

    if fake.signals:
        lines.append("")
        lines.append("**Signals flagged:**")
        for signal in fake.signals:
            lines.append(f"- {signal}")

    return lines + ["", "---"]


def _qa_insights(report: Report) -> list[str]:
    lines = ["## 🗣️ Key Q&A Insights", ""]

    if not report.qa_insights:
        lines.append("*No Q&A insights available.*")
        return lines + ["", "---"]

    for insight in report.qa_insights:
        lines.append(f"- {insight}")

    return lines + ["", "---"]


def _competitive_comparison(report: Report) -> list[str]:
    comp = report.competitive
    lines = ["## 🏅 Competitive Comparison", ""]

    if not comp or not comp.competitors:
        lines.append("*No competitive data available.*")
        return lines + ["", "---"]

    # Build the comparison table
    lines.append(
        "| Product | Price | Rating | Reviews | Fake Risk | Trend |"
    )
    lines.append("|---|---|---|---|---|---|")

    # Primary product row
    primary = report.primary_product
    primary_price = (
        f"${primary.price:.2f}"
        if primary and primary.price is not None
        else "N/A"
    )
    primary_rating = (
        _stars(report.review_summary.avg_rating)
        if report.review_summary
        else "N/A"
    )
    primary_reviews = (
        str(report.review_summary.total_reviews)
        if report.review_summary
        else "N/A"
    )
    primary_risk = (
        _risk_emoji(report.fake_signals.overall_risk)
        if report.fake_signals
        else "—"
    )
    primary_trend = (
        _trend_arrow(report.temporal.trend_direction)
        if report.temporal
        else "—"
    )

    primary_label = (primary.title[:50] + "…") if primary and len(primary.title) > 50 else (primary.title if primary else "Primary")

    lines.append(
        f"| **{primary_label}** 🔍 "
        f"| {primary_price} "
        f"| {primary_rating} "
        f"| {primary_reviews} "
        f"| {primary_risk} "
        f"| {primary_trend} |"
    )

    # Competitor rows
    for cp in comp.competitors:
        title = cp.title[:50] + "…" if len(cp.title) > 50 else cp.title
        price = f"${cp.price:.2f}" if cp.price else "N/A"
        rating = _stars(cp.avg_rating)
        reviews = str(cp.review_count) if cp.review_count else "N/A"
        risk = _risk_emoji(_score_to_risk(cp.fake_risk_score))
        trend = _trend_arrow(cp.recent_trend)
        lines.append(
            f"| {title} "
            f"| {price} "
            f"| {rating} "
            f"| {reviews} "
            f"| {risk} "
            f"| {trend} |"
        )

    # Winners
    lines.append("")
    if comp.rating_winner:
        lines.append(f"**Best rated:** {comp.rating_winner}")
    if comp.value_winner:
        lines.append(f"**Best value:** {comp.value_winner}")
    if comp.cleanest_reviews_winner:
        lines.append(f"**Cleanest reviews:** {comp.cleanest_reviews_winner}")

    return lines + ["", "---"]


def _score_to_risk(score: float) -> str:
    if score <= 0.3:
        return "low"
    elif score <= 0.6:
        return "medium"
    return "high"


def _red_flags(report: Report) -> list[str]:
    lines = ["## ⚠️ Red Flags & Caveats", ""]

    flags: list[str] = []

    # From fake signals
    fake = report.fake_signals
    if fake:
        if fake.overall_risk in ("medium", "high"):
            flags.append(
                f"Fake review risk is **{fake.overall_risk}** "
                f"(score: {fake.risk_score:.2f}) — "
                f"{fake.vine_percentage:.0f}% Vine, "
                f"{fake.unverified_percentage:.0f}% unverified"
            )
        if fake.signals:
            flags.extend(fake.signals)

    # From temporal
    temporal = report.temporal
    if temporal:
        if temporal.trend_direction == "declining":
            flags.append(
                f"⚠️ **Quality declining** — "
                f"30-day avg ({temporal.recent_30d_avg:.1f}) "
                f"vs overall ({temporal.overall_avg:.1f})"
            )
        if temporal.anomaly_months:
            flags.append(
                "📅 **Anomalous months detected:** "
                + ", ".join(temporal.anomaly_months)
            )

    # Price concerns
    product = report.primary_product
    if product and product.price is not None and product.price <= 0:
        flags.append("💸 Price is listed as $0.00 — may be inaccurate.")

    if not flags:
        flags.append("✅ No major red flags detected.")

    for flag in flags:
        lines.append(f"- {flag}")

    return lines + ["", "---"]


def _recommendation(report: Report) -> list[str]:
    lines = ["## 💡 Recommendation", ""]

    if report.competitive and report.competitive.recommendation:
        lines.append(report.competitive.recommendation)
    elif report.synthesis:
        lines.append(report.synthesis)
    else:
        lines.append("*No recommendation available.*")

    return lines + [""]


def _footer(report: Report) -> list[str]:
    gen_date = report.generated_at.strftime("%Y-%m-%d %H:%M:%S")
    return [
        "---",
        "",
        f"*Data sources: Amazon.com reviews, Q&A, product page*",
        f"*Generated: {gen_date} UTC*",
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_report(report: Report, output_path: str | None = None) -> str:
    """Generate a rich Markdown report from a Report object.

    Args:
        report: The fully-populated Report dataclass.
        output_path: If provided, the report string is written to this path.

    Returns:
        The complete markdown report as a string.
    """
    sections: list[list[str]] = [
        _header(report),
        _verdict(report),
        _quick_stats(report),
        _rating_over_time(report),
        _pros_cons(report),
        _fake_review_analysis(report),
        _qa_insights(report),
        _competitive_comparison(report),
        _red_flags(report),
        _recommendation(report),
        _footer(report),
    ]

    report_str = "\n".join(
        line for section in sections for line in section
    )

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_str)

    return report_str
