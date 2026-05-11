from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.models.product import Product, Variant

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.com"


def scrape_product_page(
    asin: str, client: "RateLimitedClient"  # noqa: F821
) -> Optional[Product]:
    """
    Scrape a full Amazon product page for the given ASIN.

    Extracts: title, brand, price, category, bullet_points, specs table,
    BS rank, main image URL, and variant information.

    Args:
        asin: The Amazon ASIN (10-character product identifier).
        client: A RateLimitedClient instance for making HTTP requests.

    Returns:
        A fully populated Product object, or None if the page returned 404
        or could not be parsed.
    """
    from src.scraper.proxy import RateLimitedClient  # noqa: F811

    url = f"{BASE_URL}/dp/{asin}"
    logger.info("Scraping product page for ASIN %s", asin)

    try:
        response = client.get(url)
        if response.status_code == 404:
            logger.warning("Product page not found for ASIN %s", asin)
            return None
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch product page for ASIN %s: %s", asin, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        title = _extract_title(soup) or ""
        brand = _extract_brand(soup) or ""
        price = _extract_price(soup)
        category = _extract_category(soup) or ""
        bullet_points = _extract_bullet_points(soup)
        specs = _extract_specs(soup)
        bs_rank = _extract_bs_rank(soup)
        main_image_url = _extract_main_image(soup)
        variants = _extract_variants(soup)
    except Exception as exc:
        logger.error("Failed to parse product page for ASIN %s: %s", asin, exc)
        return None

    product = Product(
        asin=asin,
        title=title,
        brand=brand,
        price=price,
        category=category,
        url=url,
        main_image_url=main_image_url,
        variants=variants,
        bullet_points=bullet_points,
        specs=specs,
        bs_rank=bs_rank,
    )

    logger.info(
        "Successfully scraped product %s: '%s' (${})".replace(
            "${}", str(price) if price else "N/A"
        ),
        asin,
        title[:60],
    )
    return product


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    """Extract product title using multiple selector strategies."""
    selectors = [
        "span#productTitle",
        "#productTitle",
        'h1.a-size-large span',
        'h1 span#title',
        '[data-feature-name="title"]',
        'h1.a-spacing-none',
    ]
    return _select_text(soup, selectors)


def _extract_brand(soup: BeautifulSoup) -> Optional[str]:
    """Extract brand name."""
    selectors = [
        'a#bylineInfo',
        '#bylineInfo',
        'a#brand',
        '[data-feature-name="brand"] a',
        'tr.brand-snapshot a',
        'a[href*="/stores/"]',
        'a[href*="field-lbr_brands_browse-bin"]',
    ]
    text = _select_text(soup, selectors)
    if text:
        # Clean up "Visit the X Store" -> "X"
        for prefix in ["Visit the ", " Brand", " Store"]:
            if text.endswith(prefix):
                text = text[: -len(prefix)]
            if text.startswith(prefix):
                text = text[len(prefix) :]
        # Remove common wrappers
        text = text.replace("Visit the ", "").replace(" Store", "").strip()
        return text
    return None


def _extract_price(soup: BeautifulSoup) -> Optional[float]:
    """Extract the current price as a float."""
    selectors = [
        'span.a-price span.a-offscreen',
        'span.a-price[data-a-size="xl"] span.a-offscreen',
        'span.a-price[data-a-size="large"] span.a-offscreen',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        'span#priceblock_ourprice',
        'span#priceblock_dealprice',
        '.a-price .a-offscreen',
        '.a-price-whole',
        'span.a-price',
        '[data-a-strike="true"]',
        'span.a-size-medium.a-color-price',
    ]
    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                price = _parse_price(text)
                if price is not None:
                    return price
        except Exception:
            continue
    return None


def _parse_price(text: str) -> Optional[float]:
    """Parse various Amazon price formats."""
    if not text:
        return None
    # Remove currency symbols and commas
    cleaned = text.replace("$", "").replace(",", "").strip()
    # Match the first number with decimal
    match = re.search(r"([0-9]+\.?[0-9]*)", cleaned)
    if match:
        val = float(match.group(1))
        if val > 0:
            return val
    return None


def _extract_category(soup: BeautifulSoup) -> Optional[str]:
    """Extract the breadcrumb category path."""
    selectors = [
        'ul.a-unordered-list.a-horizontal li span.a-list-item a',
        '#wayfinding-breadcrumbs_feature_div ul li a',
        '#breadcrumb li a',
        '.a-breadcrumb li a',
        '#nav-subnav a',
        '[data-feature-name="breadcrumb"] a',
    ]
    parts = []
    for selector in selectors:
        try:
            elements = soup.select(selector)
            if elements:
                for el in elements:
                    text = el.get_text(strip=True)
                    if text and text not in ("", "›"):
                        parts.append(text)
                if parts:
                    return " > ".join(parts)
        except Exception:
            continue
    return None


def _extract_bullet_points(soup: BeautifulSoup) -> list[str]:
    """Extract product bullet point features."""
    selectors = [
        'ul.a-unordered-list.a-vertical.a-spacing-small li span.a-list-item',
        '#feature-bullets ul li span.a-list-item',
        '#feature-bullets ul li',
        'div#feature-bullets li',
        '[data-feature-name="featurebullets"] li',
        'ul.a-vertical li span',
    ]
    points = []
    for selector in selectors:
        try:
            elements = soup.select(selector)
            if elements:
                for el in elements:
                    text = el.get_text(strip=True)
                    if text and len(text) > 3 and text not in points:
                        points.append(text)
                if points:
                    return points
        except Exception:
            continue
    return []


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Extract product specification table."""
    specs: dict[str, str] = {}

    # Try the product details table first
    selectors = [
        'table.a-keyvalue.prodDetTable tr',
        '#productDetails_detailBullets_sections1 tr',
        '#prodDetails tr',
        '.prodDetTable tr',
        'table.prodDetTable tr',
        '#technicalSpecifications tr',
    ]

    for selector in selectors:
        try:
            rows = soup.select(selector)
            if rows:
                for row in rows:
                    try:
                        key_el = row.select_one("th, td.a-size-base")
                        val_el = row.select_one("td, td.a-size-base")
                        # Some tables use th/td pairing
                        if not key_el or not val_el:
                            cols = row.find_all("td")
                            if len(cols) >= 2:
                                key_el, val_el = cols[0], cols[1]
                        if key_el and val_el:
                            key = key_el.get_text(strip=True)
                            val = val_el.get_text(strip=True)
                            if key and val:
                                specs[key.rstrip(":")] = val
                    except Exception:
                        continue
                if specs:
                    return specs
        except Exception:
            continue

    # Fallback: grab any definition-list style specs
    try:
        dls = soup.select("#productDetails_db_sections tr")
        for row in dls:
            try:
                cols = row.find_all("td")
                if len(cols) >= 2:
                    key = cols[0].get_text(strip=True)
                    val = cols[1].get_text(strip=True)
                    if key and val:
                        specs[key.rstrip(":")] = val
            except Exception:
                continue
    except Exception:
        pass

    return specs


def _extract_bs_rank(soup: BeautifulSoup) -> Optional[str]:
    """Extract Best Sellers Rank."""
    selectors = [
        'span#productDetails_detailBullets_sections1 tr:has(th:contains("Best Sellers Rank")) td',
        'th:contains("Best Sellers Rank") + td',
        'th:contains("Best Sellers Rank") ~ td',
        '#productDetails_detailBullets_sections1 th:contains("Best Sellers") + td',
        '#SalesRank',
        'th:contains("Best Sellers Rank")',
        'li:contains("Best Sellers Rank") span',
        'tr:has(th:-soup-contains("Best Sellers Rank")) td',
    ]
    text = _select_text(soup, selectors)
    if text:
        # Clean up the rank text
        text = text.strip()
        # Extract first rank number
        match = re.search(r"#([0-9,]+)", text)
        if match:
            return "#" + match.group(1)
        return text[:100]
    return None


def _extract_main_image(soup: BeautifulSoup) -> Optional[str]:
    """Extract the main product image URL."""
    selectors = [
        "img#landingImage",
        "#landingImage",
        'img#imgBlkFront',
        '#imgBlkFront',
        'div.imgTagWrapper img',
        '[data-feature-name="main-image"] img',
        'div#main-image-container img',
        'div#imgTagWrapperId img',
    ]
    for selector in selectors:
        try:
            img = soup.select_one(selector)
            if img:
                src = img.get("src") or img.get("data-old-hires") or ""
                if src and not src.startswith("data:"):
                    return str(src)
        except Exception:
            continue
    return None


def _extract_variants(soup: BeautifulSoup) -> list[Variant]:
    """Extract variant selector information (sizes, colors, styles)."""
    variants: list[Variant] = []

    # Look for the variation tables
    try:
        # Find variation sections
        var_sections = soup.select('div[data-feature-name="variation"], div[id*="variation"]')

        if not var_sections:
            var_sections = soup.select('div#variation_color_name, div#variation_size_name, '
                                        'div#variation_style_name, '
                                        '.a-row.a-spacing-mini[data-csa-c-type="widget"]')

        if not var_sections:
            # Broader search for any variation section
            for attr in ["color_name", "size_name", "style_name", "pattern_name"]:
                section = soup.select_one(f"div#variation_{attr}")
                if section:
                    var_sections.append(section)

        for section in var_sections:
            try:
                # Find all variant option items
                items = section.select("li.swatch-list-item, li.a-spacing-small, "
                                        "li[data-csa-c-item-id], "
                                        "li.a-dropdown-container, "
                                        "div.a-row a[href*='/dp/'], "
                                        "li[data-a-carousel-params], "
                                        "li[data-csa-c-item-name]")

                if not items:
                    # Try inline swatches
                    items = section.select("img[src*='swatch']")

                for item in items:
                    try:
                        # Extract variant ASIN from data-attribute or link
                        var_asin = item.get("data-defaultasin") or item.get("data-asin") or ""
                        if not var_asin:
                            link = item.find("a", href=True)
                            if link:
                                href = link.get("href", "")
                                m = re.search(r"/dp/([A-Z0-9]{10})", href)
                                if m:
                                    var_asin = m.group(1)

                        if not var_asin:
                            continue

                        # Extract variant name/title
                        var_name = item.get("data-title") or item.get("title") or ""
                        if not var_name:
                            title_el = item.select_one("img")
                            if title_el:
                                var_name = title_el.get("alt") or ""
                        if not var_name:
                            # Try text inside the swatch
                            text_el = item.select_one("span.a-size-base, span.a-text-bold")
                            if text_el:
                                var_name = text_el.get_text(strip=True)
                        if not var_name:
                            var_name = "Unknown Variant"

                        # Extract variant price
                        var_price = None
                        price_el = item.select_one("span.a-price span.a-offscreen, "
                                                    "span.a-price-whole, "
                                                    "span.a-color-price")
                        if price_el:
                            var_price = _parse_price(price_el.get_text(strip=True))

                        # Check availability
                        is_available = True
                        disabled = item.select_one(
                            ".a-disabled, li.disabled, .swatch-unavailable, "
                            "[aria-disabled='true']"
                        )
                        if disabled:
                            is_available = False

                        variant = Variant(
                            asin=var_asin,
                            name=var_name[:100],
                            price=var_price,
                            is_available=is_available,
                        )

                        # Avoid duplicates
                        if variant.asin not in [v.asin for v in variants]:
                            variants.append(variant)

                    except Exception:
                        continue

            except Exception:
                continue

    except Exception as exc:
        logger.debug("Error extracting variants: %s", exc)

    return variants


def _select_text(soup: BeautifulSoup, selectors: list[str]) -> Optional[str]:
    """Try multiple CSS selectors and return the first non-empty text result."""
    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if text:
                    return text
        except Exception:
            continue
    return None
