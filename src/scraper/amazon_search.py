from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.models.product import Product

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.com"


def _extract_asin_from_link(link: str) -> Optional[str]:
    """Extract ASIN from an Amazon product URL."""
    # Pattern: /dp/ASIN or /gp/product/ASIN or /exec/obidos/ASIN
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/exec/obidos/ASIN/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})",
    ]
    for pat in patterns:
        match = re.search(pat, link)
        if match:
            return match.group(1)
    # Also check if the link itself looks like an ASIN
    if re.match(r"^[A-Z0-9]{10}$", link.strip()):
        return link.strip()
    return None


def _parse_price(text: str) -> Optional[float]:
    """Parse a price string like '$19.99' or '$19.99 - $29.99' to float."""
    if not text:
        return None
    # Handle ranges - take the first price
    match = re.search(r"\$?([0-9]+\.[0-9]{2})", text.replace(",", ""))
    if match:
        return float(match.group(1))
    # Try integer price like '$20'
    match = re.search(r"\$?([0-9]+)\s", text)
    if match:
        return float(match.group(1))
    return None


def _parse_rating(text: str) -> Optional[float]:
    """Parse rating text like '4.5 out of 5 stars'."""
    if not text:
        return None
    match = re.search(r"([0-9.]+)\s*out\s*of\s*5", text)
    if match:
        return float(match.group(1))
    match = re.search(r"([0-9.]+)", text)
    if match:
        return float(match.group(1))
    return None


def _parse_review_count(text: str) -> Optional[int]:
    """Parse review count like '1,234 ratings' or '1.2k'."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9])?[kKmM]?)", text)
    if match:
        val = match.group(1)
        if val.lower().endswith("k"):
            return int(float(val[:-1]) * 1000)
        if val.lower().endswith("m"):
            return int(float(val[:-1]) * 1000000)
        return int(float(val))
    return None


def search_product(
    product_name: str, client: "RateLimitedClient"  # noqa: F821
) -> list[Product]:
    """
    Search Amazon for a product by name and return up to 10 Product objects.

    Args:
        product_name: The product name or search query to look up.
        client: A RateLimitedClient instance for making HTTP requests.

    Returns:
        A list of up to 10 Product objects with minimal data (asin, title,
        price, url). Returns an empty list if no results are found.
    """
    # Import locally to avoid circular import
    from src.scraper.proxy import RateLimitedClient  # noqa: F811

    url = f"{BASE_URL}/s?k={product_name.replace(' ', '+')}"
    logger.info("Searching Amazon for '%s' at %s", product_name, url)

    results: list[Product] = []

    try:
        response = client.get(url)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Search request failed for '%s': %s", product_name, exc)
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    result_cards = _find_result_cards(soup)

    for card in result_cards:
        if len(results) >= 10:
            break

        try:
            product = _parse_search_result_card(card)
            if product and product.asin:
                results.append(product)
        except Exception as exc:
            logger.debug("Failed to parse a search result card: %s", exc)
            continue

    logger.info("Found %d products for '%s'", len(results), product_name)
    return results


def _find_result_cards(soup: BeautifulSoup) -> list:
    """Find all product result cards on the search page using multiple selectors."""
    # Amazon frequently changes class names. Try multiple strategies.
    selectors = [
        'div[data-component-type="s-search-result"]',
        'div.s-result-item[data-asin]',
        "div.sg-col-4-of-24",
        "div.sg-col-4-of-12",
        "div.s-result-item",
        'div[data-asin]:not([data-asin=""])',
    ]

    for selector in selectors:
        cards = soup.select(selector)
        if cards:
            # Filter out empty ASINs
            valid = []
            for c in cards:
                asin = c.get("data-asin", "")
                if asin and asin.strip():
                    valid.append(c)
            if valid:
                return valid

    # Last resort: find all <a> with /dp/ links and walk up to their container
    fallback_cards = []
    for link in soup.find_all("a", href=True):
        asin = _extract_asin_from_link(link["href"])
        if asin:
            # Walk up to a reasonable container
            parent = link
            for _ in range(5):
                if parent and parent.name in ("div", "li"):
                    break
                parent = parent.parent if parent else None
            if parent and parent not in fallback_cards:
                fallback_cards.append(parent)

    return fallback_cards


def _parse_search_result_card(card) -> Optional[Product]:
    """Parse a single search result card into a Product object."""
    # Extract ASIN
    asin = card.get("data-asin", "")
    if not asin:
        # Try to find ASIN from link
        link_tag = card.find("a", href=True)
        if link_tag:
            asin = _extract_asin_from_link(link_tag["href"]) or ""
    if not asin:
        return None

    # Extract title
    title = _extract_field(card, [
        'h2 a span',
        'h2 a',
        'h2 span',
        '[data-cy="title-recipe"] a',
        'a.a-link-normal.s-underline-text',
        'span.a-size-medium',
        'span.a-size-base-plus',
    ], extract_text=True) or ""

    # Extract price
    price_text = _extract_field(card, [
        'span.a-price span.a-offscreen',
        'span.a-price[data-a-size] span.a-offscreen',
        'span.a-price-whole',
        '.a-price .a-offscreen',
        'span.a-price',
    ], extract_text=True)
    price = _parse_price(price_text) if price_text else None

    # Extract URL
    url = ""
    link_tag = card.find("a", href=True)
    if link_tag:
        href = link_tag["href"]
        if href.startswith("/"):
            url = BASE_URL + href
        elif href.startswith(BASE_URL):
            url = href
    if not url:
        url = f"{BASE_URL}/dp/{asin}"

    # Extract brand
    brand = _extract_field(card, [
        'h5[data-attribute]',
        '[data-attribute="brand"]',
        'span.a-size-small.a-color-base',
        '.s-sponsored-label-text',
        '.a-row.a-size-base a',
    ], extract_text=True) or ""

    # Extract rating
    rating_text = _extract_field(card, [
        'i.a-icon-star span',
        'i.a-icon-star',
        'span.a-icon-alt',
        '[data-cy="reviews-block"] i span',
    ], extract_text=True)
    rating = _parse_rating(rating_text) if rating_text else None

    # Extract review count
    review_count_text = _extract_field(card, [
        'span.a-size-base.s-underline-text',
        'a.a-link-normal span.a-size-base',
        'span[data-csa-c-func-deps="aui-da-a-truncate"]',
        '[data-cy="reviews-block"] span.a-size-base',
    ], extract_text=True)
    review_count = _parse_review_count(review_count_text) if review_count_text else None

    product = Product(
        asin=asin,
        title=title,
        brand=brand,
        price=price,
        url=url,
    )

    # Set rating and review count in a way compatible with the Product model
    # (Product doesn't have rating/review_count fields, so we'd use what we have)
    return product


def _extract_field(soup, selectors: list[str], extract_text: bool = False) -> Optional[str]:
    """Try multiple selectors to extract a field from the soup."""
    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if element:
                if extract_text:
                    text = element.get_text(strip=True)
                    if text:
                        return text
                else:
                    val = element.get("href") or element.get("src") or element.get("data-attribute")
                    if val:
                        return str(val)
        except Exception:
            continue
    return None
