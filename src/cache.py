from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from src.models import Product, Review


class ReviewCache:
    """SQLite-backed cache for Amazon product data and reviews."""

    def __init__(self, db_path: str = "./cache/reviews.db") -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                asin        TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                brand       TEXT NOT NULL DEFAULT '',
                price       REAL,
                category    TEXT NOT NULL DEFAULT '',
                url         TEXT NOT NULL DEFAULT '',
                main_image_url TEXT,
                variants    TEXT NOT NULL DEFAULT '[]',
                bullet_points TEXT NOT NULL DEFAULT '[]',
                specs       TEXT NOT NULL DEFAULT '{}',
                bs_rank     TEXT,
                scraped_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id   TEXT NOT NULL,
                asin        TEXT NOT NULL,
                rating      INTEGER NOT NULL,
                title       TEXT NOT NULL DEFAULT '',
                body        TEXT NOT NULL DEFAULT '',
                date        TEXT NOT NULL,
                verified_purchase INTEGER NOT NULL DEFAULT 0,
                vine_voice  INTEGER NOT NULL DEFAULT 0,
                reviewer_id TEXT NOT NULL DEFAULT '',
                reviewer_rank TEXT,
                reviewer_total_reviews INTEGER,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                images_count INTEGER NOT NULL DEFAULT 0,
                variant     TEXT,
                country     TEXT NOT NULL DEFAULT 'US',
                UNIQUE(review_id, asin)
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_asin ON reviews(asin);
            CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(date);
        """)
        conn.commit()
        conn.close()

    def get_cached_product(self, asin: str) -> Optional[Product]:
        """Retrieve a cached product by ASIN."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE asin = ?", (asin,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        scraped_at = datetime.fromisoformat(row["scraped_at"])
        variants = json.loads(row["variants"])
        bullet_points = json.loads(row["bullet_points"])
        specs = json.loads(row["specs"])

        return Product(
            asin=row["asin"],
            title=row["title"],
            brand=row["brand"],
            price=row["price"],
            category=row["category"],
            url=row["url"],
            main_image_url=row["main_image_url"],
            variants=variants,
            bullet_points=bullet_points,
            specs=specs,
            bs_rank=row["bs_rank"],
            scraped_at=scraped_at,
        )

    def cache_product(self, product: Product) -> None:
        """Insert or replace a product in the cache."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO products
               (asin, title, brand, price, category, url, main_image_url,
                variants, bullet_points, specs, bs_rank, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product.asin,
                product.title,
                product.brand,
                product.price,
                product.category,
                product.url,
                product.main_image_url,
                json.dumps([v.__dict__ for v in product.variants]),
                json.dumps(product.bullet_points),
                json.dumps(product.specs),
                product.bs_rank,
                product.scraped_at.isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def get_cached_reviews(self, asin: str) -> list[Review]:
        """Retrieve all cached reviews for an ASIN."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reviews WHERE asin = ? ORDER BY date DESC",
            (asin,),
        )
        rows = cursor.fetchall()
        conn.close()

        reviews = []
        for row in rows:
            reviews.append(
                Review(
                    review_id=row["review_id"],
                    asin=row["asin"],
                    rating=row["rating"],
                    title=row["title"],
                    body=row["body"],
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    verified_purchase=bool(row["verified_purchase"]),
                    vine_voice=bool(row["vine_voice"]),
                    reviewer_id=row["reviewer_id"],
                    reviewer_rank=row["reviewer_rank"],
                    reviewer_total_reviews=row["reviewer_total_reviews"],
                    helpful_count=row["helpful_count"],
                    images_count=row["images_count"],
                    variant=row["variant"],
                    country=row["country"],
                )
            )
        return reviews

    def cache_reviews(self, asin: str, reviews: list[Review]) -> None:
        """Insert reviews into the cache (ignore duplicates)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        for review in reviews:
            cursor.execute(
                """INSERT OR IGNORE INTO reviews
                   (review_id, asin, rating, title, body, date,
                    verified_purchase, vine_voice, reviewer_id, reviewer_rank,
                    reviewer_total_reviews, helpful_count, images_count,
                    variant, country)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review.review_id,
                    review.asin,
                    review.rating,
                    review.title,
                    review.body,
                    review.date.isoformat(),
                    int(review.verified_purchase),
                    int(review.vine_voice),
                    review.reviewer_id,
                    review.reviewer_rank,
                    review.reviewer_total_reviews,
                    review.helpful_count,
                    review.images_count,
                    review.variant,
                    review.country,
                ),
            )
        conn.commit()
        conn.close()

    def is_fresh(self, asin: str, days: int = 7) -> bool:
        """Check if a cached product was scraped within the given number of days."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT scraped_at FROM products WHERE asin = ?",
            (asin,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return False

        scraped_at = datetime.fromisoformat(row["scraped_at"])
        return datetime.now() - scraped_at < timedelta(days=days)

    def clear_old(self, days: int = 30) -> None:
        """Remove products and reviews older than the given number of days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE scraped_at < ?", (cutoff,))
        cursor.execute(
            """DELETE FROM reviews WHERE asin NOT IN
               (SELECT asin FROM products)"""
        )
        conn.commit()
        conn.close()
