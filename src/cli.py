"""Amazon Review Miner — CLI entry point and full pipeline orchestration."""

from __future__ import annotations

import argparse
import logging
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime

# Ensure project root is on sys.path for direct execution
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.analysis import (
    analyze_fakes,
    analyze_temporal,
    compare_products,
    compute_sentiment_breakdown,
    extract_pros_cons,
    generate_synthesis,
)
from src.cache import ReviewCache
from src.config import Config, load_config
from src.models.product import Product
from src.models.report import (
    CompetitiveComparison,
    FakeReviewSignals,
    Report,
    ReviewSummary,
    TemporalTrend,
)
from src.models.review import Review
from src.report_generator import generate_report
from src.scraper.amazon_search import search_product
from src.scraper.product_page import scrape_product_page
from src.scraper.proxy import RateLimitedClient
from src.scraper.qa import scrape_qa
from src.scraper.reviews import scrape_reviews

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# ASIN extraction helper
# ──────────────────────────────────────────────────────────────────────


def _extract_asin_from_url(url: str) -> str:
    """Extract a 10-character ASIN from an Amazon product URL."""
    match = re.search(r"/dp/([A-Z0-9]{10})", url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract ASIN from {url}")


# ──────────────────────────────────────────────────────────────────────
# ReviewSummary builder
# ──────────────────────────────────────────────────────────────────────


def _build_review_summary(reviews: list[Review]) -> ReviewSummary:
    """Build a ReviewSummary from a list of reviews."""
    if not reviews:
        return ReviewSummary(
            total_reviews=0,
            avg_rating=0.0,
            rating_distribution={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            verified_pct=0.0,
            vine_pct=0.0,
        )

    total = len(reviews)
    avg = sum(r.rating for r in reviews) / total
    dist = Counter(r.rating for r in reviews)
    rating_dist = {i: dist.get(i, 0) for i in range(1, 6)}
    verified_pct = sum(1 for r in reviews if r.verified_purchase) / total * 100
    vine_pct = sum(1 for r in reviews if r.vine_voice) / total * 100

    dates = [r.date for r in reviews if r.date]
    date_range = (min(dates), max(dates)) if dates else None

    return ReviewSummary(
        total_reviews=total,
        avg_rating=round(avg, 2),
        rating_distribution=rating_dist,
        verified_pct=round(verified_pct, 1),
        vine_pct=round(vine_pct, 1),
        date_range=date_range,
    )


# ──────────────────────────────────────────────────────────────────────
# Q&A insights extraction
# ──────────────────────────────────────────────────────────────────────


def _extract_qa_insights(qa_entries: list) -> list[str]:
    """Extract top Q&A entries as insight strings."""
    insights: list[str] = []
    for entry in sorted(qa_entries, key=lambda e: e.vote_count, reverse=True)[:10]:
        q = entry.question[:120]
        a = entry.answer[:200]
        insights.append(f"**Q:** {q}  \n**A:** {a}")
    return insights


# ──────────────────────────────────────────────────────────────────────
# Competitive comparison helper
# ──────────────────────────────────────────────────────────────────────


def _run_competitive_comparison(
    primary_product: Product,
    primary_reviews: list[Review],
    primary_fake: FakeReviewSignals,
    client: RateLimitedClient,
    config: Config,
) -> CompetitiveComparison | None:
    """Search for competitors, scrape their data, and return a comparison."""
    logger.info("Searching for competitors of '%s'...", primary_product.title)
    competitors = search_product(primary_product.title, client)

    # Exclude the primary product itself
    competitors = [c for c in competitors if c.asin != primary_product.asin]
    if not competitors:
        logger.warning("No competitors found for comparison.")
        return None

    # Limit to top 3 competitors
    competitors = competitors[:3]

    # Scrape competitor data
    all_products = [primary_product]
    all_reviews_map: dict[str, list[Review]] = {primary_product.asin: primary_reviews}
    all_fake_map: dict[str, FakeReviewSignals] = {primary_product.asin: primary_fake}

    comp_max_pages = min(config.scraping.max_reviews // 10, 20)  # fewer pages for competitors

    for comp in competitors:
        logger.info("Scraping competitor: %s (%s)", comp.title, comp.asin)
        try:
            comp_product = scrape_product_page(comp.asin, client)
            if comp_product:
                all_products.append(comp_product)
            comp_reviews = scrape_reviews(comp.asin, client, max_pages=comp_max_pages, batch="recent")
            all_reviews_map[comp.asin] = comp_reviews
            comp_fake = analyze_fakes(comp_reviews)
            all_fake_map[comp.asin] = comp_fake
        except Exception as exc:
            logger.warning("Failed to scrape competitor %s: %s", comp.asin, exc)
            continue

    comparison = compare_products(
        primary_asin=primary_product.asin,
        products=all_products,
        all_reviews=all_reviews_map,
        fake_results=all_fake_map,
    )
    return comparison


# ──────────────────────────────────────────────────────────────────────
# Pipeline orchestration
# ──────────────────────────────────────────────────────────────────────


def _resolve_target(
    query: str,
    client: RateLimitedClient,
    cache: ReviewCache,
    use_cache: bool,
    config: Config,
) -> Product:
    """Resolve a query (URL or search term) into a full Product.

    - If query contains 'amazon.com', extract ASIN and scrape product page.
    - Otherwise, treat it as a search term; display results and auto-pick #1.
    - Respects cache: if cached product is fresh, return it.
    """
    if "amazon.com" in query.lower():
        asin = _extract_asin_from_url(query)

        # Check cache
        if use_cache and cache.is_fresh(asin, days=config.scraping.cache_days):
            cached = cache.get_cached_product(asin)
            if cached:
                logger.info("Using cached product data for ASIN %s", asin)
                return cached

        product = scrape_product_page(asin, client)
        if product is None:
            raise RuntimeError(f"Failed to scrape product page for ASIN {asin}")
        if use_cache:
            cache.cache_product(product)
        return product

    # Search term
    logger.info("Searching Amazon for: '%s'", query)
    results = search_product(query, client)

    if not results:
        raise RuntimeError(f"No results found for query: {query}")

    # Display top results
    for i, p in enumerate(results[:5], 1):
        price_str = f"${p.price:.2f}" if p.price is not None else "N/A"
        logger.info("  %d. %s [%s] — %s", i, p.title[:80], p.asin, price_str)

    # Auto-pick the first result
    chosen = results[0]
    logger.info("Auto-selected: '%s' [%s]", chosen.title[:80], chosen.asin)

    # Check cache for the chosen product
    if use_cache and cache.is_fresh(chosen.asin, days=config.scraping.cache_days):
        cached = cache.get_cached_product(chosen.asin)
        if cached:
            logger.info("Using cached product data for ASIN %s", chosen.asin)
            return cached

    # Scrape full product page
    product = scrape_product_page(chosen.asin, client)
    if product is None:
        raise RuntimeError(f"Failed to scrape product page for ASIN {chosen.asin}")
    if use_cache:
        cache.cache_product(product)
    return product


def main() -> None:
    """Main entry point — orchestrates the full Amazon Review Miner pipeline."""
    parser = build_parser()
    args = parser.parse_args()

    # ── Setup logging ──
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not args.quiet:
        print("Amazon Review Miner v0.1")
        print(f"Query: {args.query}")
        print(f"Config: {args.config}")
        print()

    # ── 1. Load config ──
    config = load_config(args.config)

    # ── 2. Initialize RateLimitedClient ──
    client = RateLimitedClient(
        config=config.rate_limits,
        proxy_config=config.proxy,
        user_agents=config.scraping.user_agents or None,
    )

    # ── 3. Initialize ReviewCache ──
    cache = ReviewCache(db_path=config.storage.cache_db)
    use_cache = not args.no_cache

    output_path = ""

    try:
        # ── 4. Resolve target product ──
        product = _resolve_target(args.query, client, cache, use_cache, config)

        # ── 5. Scrape reviews ──
        max_pages = math.ceil(config.scraping.max_reviews / 10)
        if use_cache and cache.is_fresh(product.asin, days=config.scraping.cache_days):
            reviews = cache.get_cached_reviews(product.asin)
            logger.info(
                "Using %d cached reviews for ASIN %s",
                len(reviews),
                product.asin,
            )
        else:
            reviews = scrape_reviews(
                product.asin,
                client,
                max_pages=max_pages,
                batch="recent",
            )
            if use_cache and reviews:
                cache.cache_reviews(product.asin, reviews)

        # ── 6. Scrape Q&A ──
        qa_entries = scrape_qa(
            product.asin,
            client,
            max_pages=config.scraping.max_qa_pages,
        )

        # ── 7. Run analysis pipeline ──
        temporal = analyze_temporal(reviews)
        fake_signals = analyze_fakes(reviews)
        pros, cons = extract_pros_cons(reviews)
        sentiment_breakdown = compute_sentiment_breakdown(reviews)
        review_summary = _build_review_summary(reviews)
        qa_insights = _extract_qa_insights(qa_entries)

        # ── 8. Competitive comparison (if --compare) ──
        competitive = None
        if args.compare:
            competitive = _run_competitive_comparison(
                primary_product=product,
                primary_reviews=reviews,
                primary_fake=fake_signals,
                client=client,
                config=config,
            )

        # ── 9. Build Report ──
        report = Report(
            query=args.query,
            generated_at=datetime.now(),
            primary_product=product,
            review_summary=review_summary,
            temporal=temporal,
            fake_signals=fake_signals,
            qa_insights=qa_insights,
            pros=pros,
            cons=cons,
            sentiment_breakdown=sentiment_breakdown,
            competitive=competitive,
        )

        # ── 10. Generate synthesis ──
        report.synthesis = generate_synthesis(report, config)

        # ── 11. Generate markdown report ──
        os.makedirs(args.output_dir, exist_ok=True)
        safe_query = "".join(c if c.isalnum() else "_" for c in args.query)[:60]
        timestamp = report.generated_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_query}_{timestamp}.md"
        output_path = os.path.join(args.output_dir, filename)
        generate_report(report, output_path=output_path)

        # ── 12. Cache results (ensure fresh) ──
        if use_cache:
            cache.cache_product(product)
            if reviews:
                cache.cache_reviews(product.asin, reviews)

        # ── 13. Print output path ──
        print(f"Report generated: {output_path}")

    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=not args.quiet)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


# ──────────────────────────────────────────────────────────────────────
# Argument parser (importable for tests)
# ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Amazon Review Miner")
    parser.add_argument("query", help="Product name or Amazon URL")
    parser.add_argument("--config", default="./config.yaml", help="Path to config file")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Enable competitive comparison",
    )
    parser.add_argument(
        "--output-dir",
        default="./reports/",
        help="Directory for output reports (default: ./reports/)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching — always scrape fresh data",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error log output",
    )
    return parser


if __name__ == "__main__":
    main()
