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

    seen_asins: set[str] = set()

    for card in result_cards:
        if len(results) >= 10:
            break

        try:
            product = _parse_search_result_card(card)
            if product and product.asin and product.asin not in seen_asins:
                seen_asins.add(product.asin)
                results.append(product)
        except Exception as exc:
            logger.debug("Failed to parse a search result card: %s", exc)
            continue

    logger.info("Found %d products for '%s'", len(results), product_name)
    return results


def _find_result_cards(soup: BeautifulSoup) -> list:
    """Find all product result cards on the search page.

    Uses data-asin attribute on divs and validates ASIN format (10 uppercase alphanumeric chars).
    """
    cards = soup.select('div[data-asin]')
    cards = [c for c in cards if re.match(r'^[A-Z0-9]{10}$', c.get('data-asin', ''))]
    return cards


def _parse_search_result_card(card) -> Optional[Product]:
    """Parse a single product card div into a Product object."""
    asin = card.get('data-asin')
    if not asin:
        return None

    # Title: try h2 full text first, fall back to img alt
    title = ''
    title_el = card.select_one('h2')
    if title_el:
        title = title_el.get_text(' ', strip=True)
    if not title:
        img = card.select_one('img')
        title = (img.get('alt', '') or '').strip() if img else ''

    # Price
    price = None
    price_el = card.select_one('span.a-price > span.a-offscreen')
    if price_el:
        price_text = price_el.get_text(strip=True)
        try:
            price = float(price_text.replace('$', '').replace(',', ''))
        except ValueError:
            pass

    # Rating
    rating_text = None
    rating_el = card.select_one('span.a-icon-alt')
    if rating_el:
        rating_text = rating_el.get_text(strip=True)

    # URL
    url = ''
    link = card.select_one('a[href*="/dp/"]')
    if link:
        href = link.get('href', '')
        url = f'https://www.amazon.com{href}' if href.startswith('/') else href
    if not url:
        url = f'https://www.amazon.com/dp/{asin}'

    # Brand
    brand = _extract_field(card, [
        'h5[data-attribute]',
        '[data-attribute="brand"]',
        'span.a-size-small.a-color-base',
    ], extract_text=True) or ''

    return Product(
        asin=asin,
        title=title,
        brand=brand,
        price=price,
        url=url,
    )


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
