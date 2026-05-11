from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class QAEntry:
    question_id: str
    asin: str
    question: str
    answer: str
    answer_date: Optional[date] = None
    vote_count: int = 0
