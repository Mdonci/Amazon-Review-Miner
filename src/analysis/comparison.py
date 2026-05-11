"""Competitive comparison engine.

Compares multiple products across rating, value, and review integrity
to determine winners in each category.
"""

from __future__ import annotations

from src.models.product import Product
from src.models.report import (
    ComparedProduct,
    CompetitiveComparison,
    FakeReviewSignals,
)
from src.models.review import Review


def _compute_avg_rating(reviews: list[Review]) -> float:
    if not reviews:
        return 0.0
    return round(sum(r.rating for r in reviews) / len(reviews), 2)


def compare_products(
    primary_asin: str,
    products: list[Product],
    all_reviews: dict[str, list[Review]],
    fake_results: dict[str, FakeReviewSignals],
) -> CompetitiveComparison:
    """Compare products across rating, value, and review integrity.

    Args:
        primary_asin: The ASIN of the user's primary product.
        products: List of Product objects to compare (including primary).
        all_reviews: Dict mapping ASIN -> list of Review objects.
        fake_results: Dict mapping ASIN -> FakeReviewSignals.

    Returns:
        CompetitiveComparison with ranked competitors and winners.
    """
    compared: list[ComparedProduct] = []

    for product in products:
        asin = product.asin
        reviews = all_reviews.get(asin, [])
        fake = fake_results.get(asin)

        avg_rating = _compute_avg_rating(reviews)
        review_count = len(reviews)
        fake_risk_score = fake.risk_score if fake else 0.0
        recent_trend = fake.overall_risk if fake else "low"

        # We don't have per-product pros/cons here by default,
        # but they can be filled in by the caller if available.
        cp = ComparedProduct(
            asin=asin,
            title=product.title,
            price=product.price if product.price else 0.0,
            avg_rating=avg_rating,
            review_count=review_count,
            fake_risk_score=fake_risk_score,
            recent_trend=recent_trend,
            pros=[],
            cons=[],
        )
        compared.append(cp)

    if not compared:
        return CompetitiveComparison(primary_asin=primary_asin)

    # Determine winners
    # Rating winner: highest avg_rating
    rating_winner = max(compared, key=lambda c: c.avg_rating)

    # Value winner: highest avg_rating / price ratio (skip zero-price)
    value_candidates = [c for c in compared if c.price > 0]
    if value_candidates:
        value_winner = max(
            value_candidates, key=lambda c: c.avg_rating / c.price
        )
    else:
        value_winner = compared[0]

    # Cleanest reviews winner: lowest fake_risk_score
    cleanest_winner = min(compared, key=lambda c: c.fake_risk_score)

    # Build recommendation field (placeholder for LLM)
    recommendation = f"rating_winner:{rating_winner.asin}"

    return CompetitiveComparison(
        primary_asin=primary_asin,
        competitors=compared,
        rating_winner=rating_winner.asin,
        value_winner=value_winner.asin,
        cleanest_reviews_winner=cleanest_winner.asin,
        recommendation=recommendation,
    )
