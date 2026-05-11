"""Sentiment extraction from review text.

Extracts top pros and cons using keyword/pattern matching,
and computes a simple sentiment breakdown from ratings.
"""

from __future__ import annotations

import re
from collections import Counter

from src.models.review import Review

# ──────────────────────────────────────────────────────────────────────
# Keyword lists
# ──────────────────────────────────────────────────────────────────────

_POSITIVE_WORDS: set[str] = {
    "love", "great", "excellent", "best", "amazing", "awesome",
    "perfect", "fantastic", "wonderful", "outstanding", "impressed",
    "superb", "brilliant", "delight", "pleased", "recommend",
    "worth", "solid", "reliable", "comfortable", "durable",
    "sturdy", "easy", "simple", "fast", "quick", "convenient",
    "beautiful", "nice", "good", "happy", "satisfied", "quality",
    "favorite", "impressive", "exceptional", "phenomenal",
    "stylish", "elegant", "sleek", "clean", "fresh",
}

_NEGATIVE_WORDS: set[str] = {
    "broke", "broken", "terrible", "waste", "returned", "disappointed",
    "poor", "bad", "awful", "horrible", "useless", "cheap",
    "flimsy", "defective", "failed", "failure", "damaged",
    "worst", "regret", "avoid", "junk", "garbage", "trash",
    "overpriced", "overrated", "misleading", "fake", "scam",
    "dangerous", "unsafe", "died", "stopped", "malfunction",
    "issue", "problem", "complaint", "annoying", "frustrating",
    "difficult", "hard", "confusing", "complicated",
    "uncomfortable", "scratch", "scratchy", "noisy", "loud",
    "leak", "leaking", "rust", "stain", "smell", "odor",
    "refund", "return", "replacement",
}


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 10]


def _clean_phrase(phrase: str) -> str:
    """Normalize a phrase: lowercase, strip punctuation edges, collapse whitespace."""
    cleaned = phrase.lower().strip()
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _extract_key_phrases(
    sentences: list[str], signal_words: set[str]
) -> list[str]:
    """Return sentences that contain at least one signal word."""
    hits: list[str] = []
    for sent in sentences:
        lower = sent.lower()
        if any(word in lower for word in signal_words):
            hits.append(_clean_phrase(sent))
    return hits


def _deduplicate_and_rank(
    phrases: list[str], top_n: int = 10
) -> list[str]:
    """Count phrase frequencies, deduplicate, return top N."""
    counter = Counter(phrases)
    # Prefer longer/more specific phrases among near-duplicates
    ranked = sorted(counter.items(), key=lambda x: (-x[1], -len(x[0])))
    # Simple dedup: skip phrases that are substrings of a higher-ranked one
    result: list[str] = []
    for phrase, count in ranked:
        if len(phrase) < 5:
            continue
        is_dup = False
        for existing in result:
            if phrase in existing or existing in phrase:
                is_dup = True
                break
        if not is_dup:
            result.append(phrase)
        if len(result) >= top_n:
            break
    return result


def extract_pros_cons(reviews: list[Review]) -> tuple[list[str], list[str]]:
    """Extract top pros and cons from review text using keyword matching.

    Pros come from 4-5★ reviews; cons come from 1-2★ reviews.

    Args:
        reviews: List of Review objects.

    Returns:
        Tuple of (pros: list[str], cons: list[str]), each up to 10 items.
    """
    if not reviews:
        return [], []

    high_rating_bodies: list[str] = []
    low_rating_bodies: list[str] = []

    for r in reviews:
        if not r.body:
            continue
        if r.rating >= 4:
            high_rating_bodies.append(r.body)
        elif r.rating <= 2:
            low_rating_bodies.append(r.body)

    # Extract sentences with positive keywords from high-rating reviews
    pro_sentences: list[str] = []
    for body in high_rating_bodies:
        sentences = _split_sentences(body)
        pro_sentences.extend(_extract_key_phrases(sentences, _POSITIVE_WORDS))

    # Extract sentences with negative keywords from low-rating reviews
    con_sentences: list[str] = []
    for body in low_rating_bodies:
        sentences = _split_sentences(body)
        con_sentences.extend(_extract_key_phrases(sentences, _NEGATIVE_WORDS))

    pros = _deduplicate_and_rank(pro_sentences, top_n=10)
    cons = _deduplicate_and_rank(con_sentences, top_n=10)

    return pros, cons


def compute_sentiment_breakdown(reviews: list[Review]) -> dict:
    """Compute simple sentiment breakdown from review ratings.

    Args:
        reviews: List of Review objects.

    Returns:
        Dict with keys "positive", "neutral", "negative" and integer counts.
        4-5★ = positive, 3★ = neutral, 1-2★ = negative.
    """
    positive = sum(1 for r in reviews if r.rating >= 4)
    neutral = sum(1 for r in reviews if r.rating == 3)
    negative = sum(1 for r in reviews if r.rating <= 2)

    return {
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
    }
