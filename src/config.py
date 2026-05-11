from __future__ import annotations

from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ProxyConfig(BaseModel):
    provider: str = "decodo"
    endpoint: str = "gate.decodo.com:7000"
    username: str = "user-spfafnk5j1-country-us"
    password: str = "=l7Up0KiR9erg2rmhQ"
    rotate_ip: bool = True
    cookie_path: str = "./amazon_cookies.json"


class RateLimitConfig(BaseModel):
    queries_per_hour: int = 3
    seconds_between_pages: int = 60
    max_retries: int = 3
    retry_backoff_base: int = 30


class ScrapingConfig(BaseModel):
    max_reviews: int = 2000
    max_qa_pages: int = 5
    cache_days: int = 7
    user_agents: list[str] = []


class LLMConfig(BaseModel):
    model: str = "deepseek-v4-flash"
    provider: str = "deepseek"
    max_tokens: int = 2000


class OutputConfig(BaseModel):
    format: str = "markdown"
    report_dir: str = "./reports/"
    keep_raw_data: bool = True


class StorageConfig(BaseModel):
    cache_db: str = "./cache/reviews.db"


class Config(BaseModel):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def load_config(path: str = "./config.yaml") -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(**data)
