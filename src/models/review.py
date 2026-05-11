from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Review:
    review_id: str
    asin: str
    rating: int
    title: str
    body: str
    date: date
    verified_purchase: bool
    vine_voice: bool
    reviewer_id: str
    reviewer_rank: Optional[str] = None
    reviewer_total_reviews: Optional[int] = None
    helpful_count: int = 0
    images_count: int = 0
    variant: Optional[str] = None
    country: str = "US"
