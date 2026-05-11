"""Fake review detection via rule-based signal analysis.

Computes 7 weighted signals to detect potentially fabricated or
incentivized reviews. No external API required.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from src.models.report import FakeReviewSignals
from src.models.review import Review

# ──────────────────────────────────────────────────────────────────────
# Signal thresholds and weights (per CODER_BRIEF spec)
# ──────────────────────────────────────────────────────────────────────

_THRESHOLDS: dict[str, float] = {
    "vine_percentage": 30.0,        # >30% Vine = incentivized bias
    "unverified_percentage": 25.0,  # >25% unverified = no purchase proof
    "burst_rate": 10.0,             # >10 reviews/day = unnatural spike
    "avg_reviewer_depth": 5.0,      # <5 = inexperienced reviewers
    "one_review_account_pct": 20.0, # >20% = sock puppet indicator
    "template_text_pct": 30.0,      # >30% = same phrasing clusters
}

_WEIGHTS: dict[str, float] = {
    "vine_percentage": 0.15,
    "unverified_percentage": 0.15,
    "burst_rate": 0.20,
    "avg_reviewer_depth": 0.15,
    "one_review_account_pct": 0.15,
    "template_text_pct": 0.20,
}

# Direction: "above" means signal fires when value > threshold;
# "below" means signal fires when value < threshold.
_DIRECTION: dict[str, str] = {
    "vine_percentage": "above",
    "unverified_percentage": "above",
    "burst_rate": "above",
    "avg_reviewer_depth": "below",
    "one_review_account_pct": "above",
    "template_text_pct": "above",
}


def _compute_burst_rate(reviews: list[Review]) -> float:
    """Compute max reviews/day in any 7-day rolling window."""
    if not reviews:
        return 0.0

    # Group reviews by date
    by_date: dict[str, int] = defaultdict(int)
    for r in reviews:
        by_date[r.date.isoformat()] += 1

    sorted_dates = sorted(by_date.keys())
    if not sorted_dates:
        return 0.0

    # Build a continuous date array with counts
    from datetime import date as dt_date

    first = dt_date.fromisoformat(sorted_dates[0])
    last = dt_date.fromisoformat(sorted_dates[-1])
    days_total = (last - first).days + 1

    daily = [0] * days_total
    for d_str, cnt in by_date.items():
        d = dt_date.fromisoformat(d_str)
        idx = (d - first).days
        daily[idx] = cnt

    # Slide 7-day window
    max_rate = 0.0
    for i in range(len(daily) - 6):
        window_sum = sum(daily[i : i + 7])
        rate = window_sum / 7.0
        if rate > max_rate:
            max_rate = rate

    return max_rate


def _compute_template_text_pct(reviews: list[Review]) -> float:
    """Heuristic template detection: word-count ±20% AND shared vocabulary >80%.

    A review is flagged as template-like if it has at least one other review
    that matches both criteria.
    """
    if not reviews:
        return 0.0

    # Pre-compute word sets and counts
    bodies: list[str] = [r.body for r in reviews if r.body]
    if len(bodies) < 2:
        return 0.0

    words_data: list[tuple[set[str], int]] = []
    for body in bodies:
        words = set(body.lower().split())
        words_data.append((words, len(body.split())))

    template_count = 0
    n = len(words_data)

    for i in range(n):
        wi, ci = words_data[i]
        if ci == 0 or len(wi) == 0:
            continue
        is_template = False
        for j in range(n):
            if i == j:
                continue
            wj, cj = words_data[j]
            if cj == 0 or len(wj) == 0:
                continue
            # Word count within ±20%
            if abs(ci - cj) / max(ci, 1) > 0.20:
                continue
            # Shared vocabulary >80%
            shared = wi & wj
            union = wi | wj
            if len(union) == 0:
                continue
            if len(shared) / len(union) > 0.80:
                is_template = True
                break
        if is_template:
            template_count += 1

    return (template_count / n) * 100.0


def _compute_risk_score(signals: dict) -> tuple[float, str]:
    """Weighted scoring per CODER_BRIEF thresholds table.

    Each signal that exceeds its threshold contributes its weight.
    Score ranges 0.0 (clean) to 1.0 (fabricated).

    Args:
        signals: Dict with keys matching _THRESHOLDS keys and float values.

    Returns:
        Tuple of (risk_score: float, overall_risk: str).
    """
    score = 0.0
    for key, threshold in _THRESHOLDS.items():
        value = signals.get(key, 0.0)
        direction = _DIRECTION[key]
        if direction == "above" and value > threshold:
            score += _WEIGHTS[key]
        elif direction == "below" and value < threshold:
            score += _WEIGHTS[key]

    score = round(min(score, 1.0), 3)

    if score < 0.3:
        risk = "low"
    elif score < 0.6:
        risk = "medium"
    else:
        risk = "high"

    return score, risk


def _collect_signals(fsv: FakeReviewSignals) -> list[str]:
    """Build human-readable list of flags from a FakeReviewSignals instance."""
    flags: list[str] = []

    if fsv.vine_percentage > _THRESHOLDS["vine_percentage"]:
        flags.append(
            f"High Vine Voice presence ({fsv.vine_percentage:.1f}%) — potential incentivized bias"
        )
    if fsv.unverified_percentage > _THRESHOLDS["unverified_percentage"]:
        flags.append(
            f"High unverified purchase rate ({fsv.unverified_percentage:.1f}%) — no purchase proof"
        )
    if fsv.burst_rate > _THRESHOLDS["burst_rate"]:
        flags.append(
            f"Review burst detected ({fsv.burst_rate:.1f} reviews/day peak) — unnatural timing"
        )
    if fsv.avg_reviewer_depth < _THRESHOLDS["avg_reviewer_depth"]:
        flags.append(
            f"Low average reviewer depth ({fsv.avg_reviewer_depth:.1f}) — inexperienced reviewers"
        )
    if fsv.one_review_account_pct > _THRESHOLDS["one_review_account_pct"]:
        flags.append(
            f"High one-review account percentage ({fsv.one_review_account_pct:.1f}%) — sock puppet indicator"
        )
    if fsv.template_text_pct > _THRESHOLDS["template_text_pct"]:
        flags.append(
            f"Template-like text detected ({fsv.template_text_pct:.1f}% of reviews) — coordinated phrasing"
        )
    if fsv.suspicious_timing:
        flags.append(
            f"Suspicious timing pattern: high burst rate combined with many one-review accounts"
        )

    return flags


def analyze_fakes(reviews: list[Review]) -> FakeReviewSignals:
    """Compute all 7 fake review signals and risk score.

    Args:
        reviews: List of Review objects for a single ASIN.

    Returns:
        FakeReviewSignals with all computed values.
    """
    total = len(reviews)
    if total == 0:
        return FakeReviewSignals()

    asin = reviews[0].asin

    # --- vine_percentage ---
    vine_count = sum(1 for r in reviews if r.vine_voice)
    vine_percentage = (vine_count / total) * 100.0

    # --- unverified_percentage ---
    unverified_count = sum(1 for r in reviews if not r.verified_purchase)
    unverified_percentage = (unverified_count / total) * 100.0

    # --- burst_rate ---
    burst_rate = _compute_burst_rate(reviews)

    # --- avg_reviewer_depth ---
    depths = [
        r.reviewer_total_reviews
        for r in reviews
        if r.reviewer_total_reviews is not None
    ]
    avg_reviewer_depth = sum(depths) / len(depths) if depths else 0.0

    # --- one_review_account_pct ---
    unique_reviewers: dict[str, int] = {}
    for r in reviews:
        if r.reviewer_total_reviews is not None:
            unique_reviewers[r.reviewer_id] = r.reviewer_total_reviews
        elif r.reviewer_id not in unique_reviewers:
            # If we don't know their total, we can't count them as one-review
            unique_reviewers[r.reviewer_id] = 0  # mark as unknown
    # Count where explicit total == 1
    one_review_count = sum(
        1 for total in unique_reviewers.values() if total == 1
    )
    one_review_account_pct = (
        (one_review_count / len(unique_reviewers)) * 100.0
        if unique_reviewers
        else 0.0
    )

    # --- template_text_pct ---
    template_text_pct = _compute_template_text_pct(reviews)

    # --- suspicious_timing ---
    suspicious_timing = (
        burst_rate > _THRESHOLDS["burst_rate"]
        and one_review_account_pct > _THRESHOLDS["one_review_account_pct"]
    )

    # --- risk score ---
    signal_values = {
        "vine_percentage": vine_percentage,
        "unverified_percentage": unverified_percentage,
        "burst_rate": burst_rate,
        "avg_reviewer_depth": avg_reviewer_depth,
        "one_review_account_pct": one_review_account_pct,
        "template_text_pct": template_text_pct,
    }
    risk_score, overall_risk = _compute_risk_score(signal_values)

    # Build the result
    fsv = FakeReviewSignals(
        asin=asin,
        vine_percentage=round(vine_percentage, 1),
        unverified_percentage=round(unverified_percentage, 1),
        burst_rate=round(burst_rate, 1),
        avg_reviewer_depth=round(avg_reviewer_depth, 1),
        one_review_account_pct=round(one_review_account_pct, 1),
        template_text_pct=round(template_text_pct, 1),
        suspicious_timing=suspicious_timing,
        overall_risk=overall_risk,
        risk_score=risk_score,
    )

    # Attach human-readable signals
    fsv.signals = _collect_signals(fsv)

    return fsv
