from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PricePoint:
    price: float
    date: datetime


@dataclass
class Variant:
    asin: str
    name: str
    price: Optional[float] = None
    is_available: bool = True


@dataclass
class Product:
    asin: str
    title: str
    brand: str
    price: Optional[float] = None
    price_history: list[PricePoint] = field(default_factory=list)
    category: str = ""
    url: str = ""
    main_image_url: Optional[str] = None
    variants: list[Variant] = field(default_factory=list)
    bullet_points: list[str] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    bs_rank: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)
