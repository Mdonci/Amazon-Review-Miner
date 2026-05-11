"""Temporal trend analysis for Amazon reviews.

Buckets reviews by month, detects trend direction via linear regression,
and flags anomaly months with unusual review volumes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from scipy.stats import linregress

from src.models.report import MonthlyBucket, TemporalTrend
from src.models.review import Review


def _bucket_by_month(reviews: list[Review]) -> list[MonthlyBucket]:
    """Group reviews by YYYY-MM and compute aggregated stats per month."""
    if not reviews:
        return []

    monthly: dict[str, list[Review]] = defaultdict(list)
    for r in reviews:
        key = r.date.strftime("%Y-%m")
        monthly[key].append(r)

    buckets: list[MonthlyBucket] = []
    for year_month in sorted(monthly.keys()):
        month_reviews = monthly[year_month]
        count = len(month_reviews)
        avg_rating = sum(r.rating for r in month_reviews) / count

        dist: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in month_reviews:
            dist[r.rating] = dist.get(r.rating, 0) + 1

        buckets.append(
            MonthlyBucket(
                year_month=year_month,
                avg_rating=round(avg_rating, 2),
                review_count=count,
                rating_distribution=dist,
            )
        )

    return buckets


def analyze_temporal(reviews: list[Review]) -> TemporalTrend:
    """Run full temporal analysis on a list of reviews.

    Args:
        reviews: List of Review objects for a single ASIN.

    Returns:
        TemporalTrend with monthly buckets, trend direction, and anomaly flags.
    """
    if not reviews:
        return TemporalTrend()

    asin = reviews[0].asin
    today = date.today()

    # Compute overall average
    overall_avg = sum(r.rating for r in reviews) / len(reviews)

    # Bucket by month
    monthly_data = _bucket_by_month(reviews)

    # Linear regression on monthly averages
    months_idx = list(range(len(monthly_data)))
    monthly_avgs = [b.avg_rating for b in monthly_data]

    trend_direction = "stable"
    if len(monthly_avgs) >= 2:
        result = linregress(months_idx, monthly_avgs)
        slope = result.slope
        if slope > 0.005:
            trend_direction = "improving"
        elif slope < -0.005:
            trend_direction = "declining"
        else:
            trend_direction = "stable"

    # Recent 30-day and 90-day averages
    cutoff_30d = today - timedelta(days=30)
    cutoff_90d = today - timedelta(days=90)

    recent_30 = [r for r in reviews if r.date >= cutoff_30d]
    recent_90 = [r for r in reviews if r.date >= cutoff_90d]

    recent_30d_avg = (
        sum(r.rating for r in recent_30) / len(recent_30) if recent_30 else 0.0
    )
    recent_90d_avg = (
        sum(r.rating for r in recent_90) / len(recent_90) if recent_90 else 0.0
    )
    recent_30d_count = len(recent_30)

    # Anomaly detection: flag months where count > 3 std dev above mean
    counts = [b.review_count for b in monthly_data]
    anomaly_months: list[str] = []
    if len(counts) >= 2:
        mean_count = np.mean(counts)
        std_count = np.std(counts, ddof=0)
        if std_count > 0:
            threshold = mean_count + 3 * std_count
            for b in monthly_data:
                if b.review_count > threshold:
                    anomaly_months.append(b.year_month)

    return TemporalTrend(
        asin=asin,
        monthly_data=monthly_data,
        trend_direction=trend_direction,
        recent_30d_avg=round(recent_30d_avg, 2),
        recent_90d_avg=round(recent_90d_avg, 2),
        overall_avg=round(overall_avg, 2),
        recent_30d_count=recent_30d_count,
        anomaly_months=anomaly_months,
    )
