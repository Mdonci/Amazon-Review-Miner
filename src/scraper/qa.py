from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from src.models.qa import QAEntry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.com"


def scrape_qa(
    asin: str,
    client: "RateLimitedClient",  # noqa: F821
    max_pages: int = 5,
) -> list[QAEntry]:
    """
    Scrape Amazon Q&A section for a given ASIN.

    Args:
        asin: The Amazon ASIN (10-character product identifier).
        client: A RateLimitedClient instance for making HTTP requests.
        max_pages: Maximum number of Q&A pages to scrape (default: 5).

    Returns:
        A list of QAEntry objects extracted from the Q&A pages.
    """
    from src.scraper.proxy import RateLimitedClient  # noqa: F811

    base_url = (
        f"{BASE_URL}/ask/questions/asin/{asin}"
        f"?ref=cm_cd_ql_qc_dp_d_ln&isAnswered=true"
    )

    all_entries: list[QAEntry] = []
    seen_questions: set[str] = set()

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            page_url = base_url
        else:
            page_url = f"{base_url}&pageNumber={page_num}"

        logger.info(
            "Scraping Q&A page %d/%d for ASIN %s",
            page_num,
            max_pages,
            asin,
        )

        try:
            response = client.get(page_url)
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Failed to fetch Q&A page %d for ASIN %s: %s",
                page_num,
                asin,
                exc,
            )
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # Detect if Q&A section is empty
        if _detect_no_qa(soup):
            logger.info(
                "No Q&A content found on page %d for ASIN %s",
                page_num,
                asin,
            )
            break

        page_entries = _parse_qa_page(soup, asin)
        if not page_entries:
            logger.info(
                "No Q&A entries parsed on page %d for ASIN %s — stopping",
                page_num,
                asin,
            )
            break

        # Deduplicate by question text
        new_entries = []
        for entry in page_entries:
            q_key = entry.question.strip().lower()[:100]
            if q_key not in seen_questions:
                seen_questions.add(q_key)
                new_entries.append(entry)

        if not new_entries:
            logger.info(
                "All entries on page %d were duplicates — stopping for ASIN %s",
                page_num,
                asin,
            )
            break

        all_entries.extend(new_entries)
        logger.info(
            "Page %d: extracted %d new Q&A entries (total: %d) for ASIN %s",
            page_num,
            len(new_entries),
            len(all_entries),
            asin,
        )

        # Check for next page
        if not _has_next_page(soup):
            logger.info(
                "No more Q&A pages for ASIN %s after page %d",
                asin,
                page_num,
            )
            break

    logger.info(
        "Finished scraping Q&A for ASIN %s: %d total entries",
        asin,
        len(all_entries),
    )
    return all_entries


def _detect_no_qa(soup: BeautifulSoup) -> bool:
    """Check if the page indicates no Q&A content is available."""
    indicators = [
        "span:contains('There are no questions')",
        "span:contains('No questions')",
        "div.a-alert-warning:has(span:contains('question'))",
        "div:contains('No one has asked a question yet')",
        "div:contains('Be the first to ask')",
    ]
    for selector in indicators:
        try:
            el = soup.select_one(selector)
            if el:
                return True
        except Exception:
            continue
    return False


def _has_next_page(soup: BeautifulSoup) -> bool:
    """Check if there is a next page link available."""
    selectors = [
        "li.a-last a",
        ".a-pagination .a-last a",
        "a[href*='&pageNumber=']:not([href*='pageNumber=1'])",
        "li.a-last:not(.a-disabled)",
    ]
    for selector in selectors:
        try:
            el = soup.select_one(selector)
            if el:
                parent = el.parent
                if parent and "a-disabled" in parent.get("class", []):
                    return False
                return True
        except Exception:
            continue
    return False


def _parse_qa_page(soup: BeautifulSoup, asin: str) -> list[QAEntry]:
    """Parse all Q&A entries from a Q&A listing page."""
    entries: list[QAEntry] = []

    # Find Q&A cards using multiple possible selectors
    cards = _find_qa_cards(soup)

    for card in cards:
        try:
            entry = _parse_single_qa(card, asin)
            if entry:
                entries.append(entry)
        except Exception as exc:
            logger.debug("Failed to parse a Q&A card: %s", exc)
            continue

    return entries


def _find_qa_cards(soup: BeautifulSoup) -> list:
    """Find individual Q&A cards using multiple selectors."""
    selectors = [
        'div[data-csa-c-type="question"]',
        'div.a-section.askQuestions',
        'div.a-fixed-left-grid-inner',
        '.a-section.a-spacing-large',
        'div.celwidget',
        # Broader: question blocks
        'div.a-row:has(span.a-size-base:contains("?"))',
        'div[data-hook="question-block"]',
    ]

    for selector in selectors:
        try:
            cards = soup.select(selector)
            if cards:
                # Filter: must contain a question-like element
                valid = []
                for c in cards:
                    text = c.get_text(strip=True)
                    if len(text) > 10 and "?" in text:
                        valid.append(c)
                if valid:
                    return valid
        except Exception:
            continue

    # Fallback: find all question sections by looking for answer buttons
    fallback_cards = []
    for el in soup.find_all(["div", "li"], class_=True):
        try:
            class_str = " ".join(el.get("class", []))
            if "question" in class_str.lower() or "qa" in class_str.lower():
                text = el.get_text(strip=True)
                if len(text) > 20 and "?" in text:
                    fallback_cards.append(el)
        except Exception:
            continue

    return fallback_cards


def _parse_single_qa(card, asin: str) -> Optional[QAEntry]:
    """Parse a single Q&A card into a QAEntry object."""
    # Extract question
    question = _get_text(card, [
        'span.a-size-base.askVote',
        'span.a-size-base[data-hook="question-title"]',
        'span.a-size-base:has(~ span)',
        '.a-size-base.a-link-normal',
        'span.a-size-base',
        'a.a-link-normal[href*="/ask/questions"]',
    ])
    if not question:
        # Try getting text that contains a question mark
        for el in card.find_all(["span", "a", "div"]):
            text = el.get_text(strip=True)
            if "?" in text and len(text) > 10:
                question = text
                break

    if not question:
        return None

    # Generate a question ID from the ASIN and question hash
    question_id = f"qa_{asin}_{hash(question) % (10**10)}"

    # Extract answer
    answer = _get_text(card, [
        'div.a-row.a-spacing-small.a-size-base',
        'span.a-size-base.a-spacing-small',
        '.a-spacing-small.a-size-base',
        '.a-size-base:not(:has(span))',
        'div[data-hook="answer-content"]',
        'span[data-hook="answer-text"]',
    ])
    if not answer:
        # Try to find answer by looking for text after "Answer:" or similar
        for el in card.find_all(["div", "span"]):
            text = el.get_text(strip=True)
            if len(text) > 20 and text != question and "?" not in text:
                parent_classes = el.parent.get("class", []) if el.parent else []
                class_str = " ".join(parent_classes) if isinstance(parent_classes, list) else str(parent_classes)
                if "answer" in class_str.lower() or "response" in class_str.lower():
                    answer = text
                    break
        if not answer:
            # Last resort: take longest text block that isn't the question
            texts = []
            for el in card.find_all(["div", "span", "p"]):
                t = el.get_text(strip=True)
                if t and t != question and len(t) > 10:
                    texts.append(t)
            if texts:
                answer = max(texts, key=len)

    # Extract answer date
    answer_date = None
    date_text = _get_text(card, [
        'span.a-size-small.a-color-secondary',
        '.a-color-secondary .a-size-small',
        'span.a-color-secondary:has(span)',
        '.a-size-small',
    ])
    if date_text:
        # Amazon dates: "Answered on January 15, 2024"
        answer_date = _parse_qa_date(date_text)

    # Extract vote count
    vote_count = 0
    vote_text = _get_text(card, [
        'span.askVote',
        'span.a-size-small.askVote',
        '.a-size-small.askVote',
        'span.vote-count',
        'span[data-hook="vote-count"]',
    ])
    if vote_text:
        match = re.search(r"([0-9]+)", vote_text.replace(",", ""))
        if match:
            try:
                vote_count = int(match.group(1))
            except (ValueError, TypeError):
                vote_count = 0

    return QAEntry(
        question_id=question_id,
        asin=asin,
        question=question[:500] if question else "",
        answer=answer[:2000] if answer else "",
        answer_date=answer_date,
        vote_count=vote_count,
    )


def _parse_qa_date(date_text: str) -> Optional[date]:
    """Parse Amazon Q&A date formats."""
    if not date_text:
        return None

    # "Answered on January 15, 2024"
    patterns = [
        r"(?:Answered\s+on\s+)?(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        r"(\d{1,2})\s+(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)\s+(\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, date_text, re.IGNORECASE)
        if match:
            try:
                groups = match.groups()
                months = {
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "may": 5, "june": 6, "july": 7, "august": 8,
                    "september": 9, "october": 10, "november": 11, "december": 12,
                }

                if groups[0].isalpha():
                    month_str = groups[0]
                    day = int(groups[1])
                    year = int(groups[2])
                else:
                    month_str = groups[1]
                    day = int(groups[0])
                    year = int(groups[2])

                month = months.get(month_str.lower())
                if month:
                    return date(year, month, day)
            except (ValueError, TypeError):
                continue

    return None


def _get_text(soup, selectors: list[str]) -> str:
    """Try multiple selectors and return the first non-empty text."""
    for selector in selectors:
        try:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text
        except Exception:
            continue
    return ""
