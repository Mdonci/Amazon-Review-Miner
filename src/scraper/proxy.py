from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from src.config import ProxyConfig, RateLimitConfig

logger = logging.getLogger(__name__)

# Default User-Agent list (rotated per request)
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


class RateLimiter:
    """Tracks request rate and enforces delays between requests."""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self.request_times: list[datetime] = []
        self.last_request_time: Optional[datetime] = None

    def wait_if_needed(self) -> None:
        """Block until it is safe to make the next request."""
        now = datetime.now()

        # Enforce queries-per-hour limit
        cutoff = now - timedelta(hours=1)
        self.request_times = [t for t in self.request_times if t > cutoff]

        if len(self.request_times) >= self.config.queries_per_hour:
            oldest = self.request_times[0]
            wait = (oldest + timedelta(hours=1) - now).total_seconds()
            if wait > 0:
                logger.info("Rate limit hit — sleeping %.1f seconds", wait)
                time.sleep(wait)

        # Enforce delay between pages
        if self.last_request_time is not None:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            if elapsed < self.config.seconds_between_pages:
                delay = self.config.seconds_between_pages - elapsed
                logger.debug("Waiting %.1f seconds between pages", delay)
                time.sleep(delay)

        self.request_times.append(datetime.now())
        self.last_request_time = datetime.now()


class RateLimitedClient:
    """HTTP client with rate limiting, User-Agent rotation, proxy support,
    and retry with exponential backoff."""

    def __init__(
        self,
        config: RateLimitConfig,
        proxy_config: ProxyConfig,
        user_agents: Optional[list[str]] = None,
    ) -> None:
        self.config = config
        self.proxy_config = proxy_config
        self.rate_limiter = RateLimiter(config)
        self.user_agents = user_agents or list(DEFAULT_USER_AGENTS)

        # Build proxy URL if configured
        client_kwargs: dict = {}
        if proxy_config.url:
            client_kwargs["proxies"] = proxy_config.url

        self.client = httpx.Client(**client_kwargs, timeout=30.0)

    def _get_user_agent(self) -> str:
        """Pick a random User-Agent string."""
        return random.choice(self.user_agents)

    def get(self, url: str, **kwargs) -> httpx.Response:
        """Make a rate-limited GET request with retry logic."""
        self.rate_limiter.wait_if_needed()

        headers = kwargs.pop("headers", {})
        if "User-Agent" not in headers:
            headers["User-Agent"] = self._get_user_agent()

        last_exc: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                logger.debug(
                    "GET %s (attempt %d/%d)",
                    url,
                    attempt + 1,
                    self.config.max_retries + 1,
                )
                response = self.client.get(url, headers=headers, **kwargs)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    logger.warning(
                        "HTTP 429 on %s — retrying after %ds", url, retry_after
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response

            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                logger.warning(
                    "Request failed for %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self.config.max_retries + 1,
                    exc,
                )
                if attempt < self.config.max_retries:
                    backoff = self.config.retry_backoff_base * (2**attempt)
                    jitter = random.uniform(0, 0.5 * backoff)
                    sleep_time = backoff + jitter
                    logger.info("Backing off %.1f seconds", sleep_time)
                    time.sleep(sleep_time)

        raise RuntimeError(
            f"Failed to fetch {url} after {self.config.max_retries + 1} attempts"
        ) from last_exc

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()

    def __enter__(self) -> "RateLimitedClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
