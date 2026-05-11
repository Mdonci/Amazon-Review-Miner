from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .product import Product


@dataclass
class ReviewSummary:
    total_reviews: int
    avg_rating: float
    rating_distribution: dict[int, int]
    verified_pct: float
    vine_pct: float
    date_range: tuple[date, date] | None = None


@dataclass
class MonthlyBucket:
    year_month: str = ""
    avg_rating: float = 0.0
    review_count: int = 0
    rating_distribution: dict[int, int] = field(default_factory=dict)


@dataclass
class TemporalTrend:
    asin: str = ""
    monthly_data: list[MonthlyBucket] = field(default_factory=list)
    trend_direction: str = "stable"
    recent_30d_avg: float = 0.0
    recent_90d_avg: float = 0.0
    overall_avg: float = 0.0
    recent_30d_count: int = 0
    anomaly_months: list[str] = field(default_factory=list)


@dataclass
class FakeReviewSignals:
    asin: str = ""
    vine_percentage: float = 0.0
    unverified_percentage: float = 0.0
    burst_rate: float = 0.0
    avg_reviewer_depth: float = 0.0
    one_review_account_pct: float = 0.0
    template_text_pct: float = 0.0
    suspicious_timing: bool = False
    overall_risk: str = "low"
    risk_score: float = 0.0
    signals: list[str] = field(default_factory=list)


@dataclass
class ComparedProduct:
    asin: str
    title: str
    price: float = 0.0
    avg_rating: float = 0.0
    review_count: int = 0
    fake_risk_score: float = 0.0
    recent_trend: str = "stable"
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)


@dataclass
class CompetitiveComparison:
    primary_asin: str = ""
    competitors: list[ComparedProduct] = field(default_factory=list)
    rating_winner: str = ""
    value_winner: str = ""
    cleanest_reviews_winner: str = ""
    recommendation: str = ""


@dataclass
class Report:
    query: str
    generated_at: datetime = datetime.now()
    primary_product: Product | None = None
    review_summary: ReviewSummary | None = None
    temporal: TemporalTrend | None = None
    fake_signals: FakeReviewSignals | None = None
    qa_insights: list[str] = field(default_factory=list)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    sentiment_breakdown: dict = field(default_factory=dict)
    competitive: CompetitiveComparison | None = None
    synthesis: str = ""
    raw_data_path: str = ""
