from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from src.models.review import Review

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.com"


def scrape_reviews(
    asin: str,
    client: "RateLimitedClient",  # noqa: F821
    max_pages: int = 50,
    batch: str = "recent",
) -> list[Review]:
    """
    Scrape Amazon product reviews for a given ASIN.

    Pages through all available review pages up to max_pages, respecting
    rate limits via the RateLimitedClient.

    Args:
        asin: The Amazon ASIN (10-character product identifier).
        client: A RateLimitedClient instance for making HTTP requests.
        max_pages: Maximum number of review pages to scrape (default: 50).
        batch: Sort order - "recent" or "helpful" (default: "recent").

    Returns:
        A list of Review objects extracted from the review pages.
    """
    from src.scraper.proxy import RateLimitedClient  # noqa: F811

    sort_map = {
        "recent": "recent",
        "helpful": "helpful",
        "positive": "positive",
        "critical": "critical",
    }
    sort_by = sort_map.get(batch, "recent")

    base_url = (
        f"{BASE_URL}/product-reviews/{asin}/ref=cm_cr_dp_d_show_all_btm"
        f"?ie=UTF8&reviewerType=all_reviews&sortBy={sort_by}"
    )

    all_reviews: list[Review] = []
    seen_review_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        page_url = f"{base_url}&pageNumber={page_num}"
        logger.info(
            "Scraping reviews page %d/%d for ASIN %s",
            page_num,
            max_pages,
            asin,
        )

        try:
            response = client.get(page_url)
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Failed to fetch reviews page %d for ASIN %s: %s",
                page_num,
                asin,
                exc,
            )
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # Detect no-review-available state
        no_reviews = _detect_no_reviews(soup)
        if no_reviews:
            logger.info("No more reviews found on page %d for ASIN %s", page_num, asin)
            break

        page_reviews = _parse_review_page(soup, asin)
        if not page_reviews:
            logger.info(
                "No reviews parsed on page %d for ASIN %s — stopping",
                page_num,
                asin,
            )
            break

        # Deduplicate
        new_reviews = []
        for r in page_reviews:
            if r.review_id not in seen_review_ids:
                seen_review_ids.add(r.review_id)
                new_reviews.append(r)

        if not new_reviews:
            logger.info(
                "All reviews on page %d were duplicates — stopping for ASIN %s",
                page_num,
                asin,
            )
            break

        all_reviews.extend(new_reviews)
        logger.info(
            "Page %d: extracted %d new reviews (total: %d) for ASIN %s",
            page_num,
            len(new_reviews),
            len(all_reviews),
            asin,
        )

        # Check if there's a next page
        if not _has_next_page(soup):
            logger.info(
                "No more pages for ASIN %s after page %d",
                asin,
                page_num,
            )
            break

    logger.info(
        "Finished scraping reviews for ASIN %s: %d total reviews",
        asin,
        len(all_reviews),
    )
    return all_reviews


def _detect_no_reviews(soup: BeautifulSoup) -> bool:
    """Check if the page indicates no reviews are available."""
    indicators = [
        "div#noReviewsPlaceholder",
        "div.a-row:has(span:contains('No customer reviews'))",
        "span:contains('There are no reviews yet')",
        "span:contains('No reviews')",
        "div.a-alert-warning",
    ]
    for selector in indicators:
        try:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True).lower()
                if "no" in text and ("review" in text or "customer" in text):
                    return True
        except Exception:
            continue
    return False


def _has_next_page(soup: BeautifulSoup) -> bool:
    """Check if there is a next page link available."""
    selectors = [
        "li.a-last a",
        "a[href*='&pageNumber=']:has(span:contains('Next'))",
        ".a-pagination .a-last a",
        "li.a-last:not(.a-disabled)",
    ]
    for selector in selectors:
        try:
            el = soup.select_one(selector)
            if el:
                # Check it's not disabled
                parent = el.parent
                if parent and "a-disabled" in parent.get("class", []):
                    return False
                return True
        except Exception:
            continue
    return False


def _parse_review_page(soup: BeautifulSoup, asin: str) -> list[Review]:
    """Parse all review cards from a review listing page."""
    reviews: list[Review] = []

    # Find review cards using multiple possible selectors
    cards = _find_review_cards(soup)

    for card in cards:
        try:
            review = _parse_single_review(card, asin)
            if review:
                reviews.append(review)
        except Exception as exc:
            logger.debug("Failed to parse a review card: %s", exc)
            continue

    return reviews


def _find_review_cards(soup: BeautifulSoup) -> list:
    """Find individual review cards using multiple selectors."""
    selectors = [
        'div[data-hook="review"]',
        'div.review',
        '.a-section.review',
        'div[data-asin]:has(div[data-hook="review-body"])',
        'div.a-section.a-spacing-none:has(i.a-icon-star)',
        'div.celwidget',
        'div[data-hook="cr-review-widget"] div.review',
        # Fallback: look for structured review containers
        'div[data-hook="review-collapsed"]',
    ]

    for selector in selectors:
        try:
            cards = soup.select(selector)
            if cards:
                # Filter out non-review cards
                valid = []
                for c in cards:
                    # Must have a rating element
                    if c.select_one('[data-hook="review-star-rating"], '
                                     'i.a-icon-star, '
                                     'span.a-icon-alt'):
                        valid.append(c)
                if valid:
                    return valid
        except Exception:
            continue

    return []


def _parse_single_review(card, asin: str) -> Optional[Review]:
    """Parse a single review card into a Review object."""
    # Review ID — from data-asin attribute, or a hash of content
    review_id = card.get("data-asin") or card.get("id") or ""
    if not review_id:
        # Try to generate a stable ID from the card content
        title_el = _find_in_card(card, [
            '[data-hook="review-title"]',
            'a.review-title',
            'span.review-title',
            '.a-text-bold',
        ])
        date_el = _find_in_card(card, [
            '[data-hook="review-date"]',
            'span.review-date',
            '.review-date',
        ])
        # Generate hash-like ID
        content_seed = ""
        if title_el:
            content_seed += title_el.get_text(strip=True)
        if date_el:
            content_seed += date_el.get_text(strip=True)
        if content_seed:
            review_id = str(hash(content_seed))
        else:
            return None

    review_id = str(review_id).strip()

    # Rating
    rating = 0
    rating_text = _get_text(card, [
        '[data-hook="review-star-rating"]',
        'i.a-icon-star span',
        'span.a-icon-alt',
        '[class*="a-icon-star"]',
    ])
    if rating_text:
        match = re.search(r"([0-9.]+)\s*out\s*of\s*5", rating_text)
        if match:
            try:
                rating = int(round(float(match.group(1))))
            except (ValueError, TypeError):
                rating = 0
        else:
            match = re.search(r"([0-9.]+)", rating_text)
            if match:
                try:
                    rating = int(round(float(match.group(1))))
                except (ValueError, TypeError):
                    rating = 0

    rating = max(1, min(5, rating))  # Clamp 1-5

    # Title
    title = _get_text(card, [
        '[data-hook="review-title"]',
        'a.review-title',
        'span.review-title',
        '.a-text-bold span',
    ])
    # Clean title (remove "5.0 out of 5 stars" prefix that Amazon sometimes includes)
    if title:
        title = re.sub(r"^[0-9.]+ out of 5 stars\s*", "", title).strip()

    # Body
    body = _get_text(card, [
        '[data-hook="review-body"]',
        'span.review-text',
        '.review-text',
        'div.review-text',
        '.a-spacing-top-mini',
    ])

    # Date
    review_date = None
    date_text = _get_text(card, [
        '[data-hook="review-date"]',
        'span.review-date',
        '.review-date',
    ])
    if date_text:
        review_date = _parse_date(date_text)

    # Verified purchase
    verified_text = _get_text(card, [
        '[data-hook="avp-badge"]',
        'span.a-size-mini.a-color-state',
        '.a-color-state',
    ])
    verified_purchase = bool(verified_text and "verified" in verified_text.lower())

    # Vine Voice
    vine_text = _get_text(card, [
        '[data-hook="vine-voice-badge"]',
        'span:contains("Vine")',
    ])
    vine_voice = bool(vine_text and "vine" in vine_text.lower())

    # Reviewer ID and name
    reviewer_id = ""
    reviewer_name = ""
    reviewer_link = _find_in_card(card, [
        '[data-hook="review-author"]',
        'a.a-profile',
        'span.a-profile-name',
    ])
    if reviewer_link:
        # Try to get reviewer ID from href
        href = ""
        if reviewer_link.name == "a":
            href = reviewer_link.get("href", "")
        else:
            parent_a = reviewer_link.find_parent("a")
            if parent_a:
                href = parent_a.get("href", "")
        if href:
            # Amazon reviewer URLs contain a numeric/alpha ID
            match = re.search(r"/profile/([A-Za-z0-9]+)", href)
            if match:
                reviewer_id = match.group(1)
        reviewer_name = reviewer_link.get_text(strip=True)

    if not reviewer_id:
        reviewer_id = f"unknown_{review_id[:8]}"

    # Helpful count
    helpful_count = 0
    helpful_text = _get_text(card, [
        '[data-hook="helpful-vote-statement"]',
        'span.cr-vote-text',
        'span.a-size-base[data-hook="helpful-vote"]',
    ])
    if helpful_text:
        match = re.search(r"([0-9,]+)", helpful_text.replace(",", ""))
        if match:
            try:
                helpful_count = int(match.group(1))
            except (ValueError, TypeError):
                helpful_count = 0

    # Variant (if review mentions which variant was purchased)
    variant = _get_text(card, [
        '[data-hook="format-strip"]',
        'a.a-size-mini.a-link-normal',
    ])
    if variant and "|" in variant:
        # Format is often "Color: Red | Size: XL"
        variant = variant.strip()

    return Review(
        review_id=review_id,
        asin=asin,
        rating=rating,
        title=title or "",
        body=body or "",
        date=review_date or date.today(),
        verified_purchase=verified_purchase,
        vine_voice=vine_voice,
        reviewer_id=reviewer_id,
        helpful_count=helpful_count,
        variant=variant or None,
    )


def _parse_date(date_text: str) -> Optional[date]:
    """Parse Amazon review date formats into a date object."""
    if not date_text:
        return None

    date_text = date_text.strip()

    # Format: "Reviewed in the United States on January 15, 2024"
    patterns = [
        r"(?:Reviewed\s+in\s+.+\s+on\s+)?(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        r"(\d{1,2})\s+(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)\s+(\d{4})",
        r"(\d{4})-(\d{2})-(\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, date_text, re.IGNORECASE)
        if match:
            try:
                if pattern == patterns[2]:
                    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                groups = match.groups()
                if groups[0].isalpha():
                    # Month name first
                    month_str = groups[0]
                    day = int(groups[1])
                    year = int(groups[2])
                else:
                    month_str = groups[1]
                    day = int(groups[0])
                    year = int(groups[2])

                months = {
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "may": 5, "june": 6, "july": 7, "august": 8,
                    "september": 9, "october": 10, "november": 11, "december": 12,
                }
                month = months.get(month_str.lower())
                if month:
                    return date(year, month, day)
            except (ValueError, TypeError):
                continue

    return None


def _get_text(soup, selectors: list[str]) -> str:
    """Try multiple selectors and return the first non-empty text."""
    el = _find_in_card(soup, selectors)
    if el:
        return el.get_text(strip=True)
    return ""


def _find_in_card(card, selectors: list[str]):
    """Find an element in a card using multiple CSS selectors."""
    for selector in selectors:
        try:
            el = card.select_one(selector)
            if el:
                return el
        except Exception:
            continue
    return None
