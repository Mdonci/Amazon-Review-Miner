# Amazon Review Miner — CODER_BRIEF

> Full-system spec. Build everything detailed below. No shortcuts.

## Overview

A CLI tool that takes an Amazon product name or product URL, finds relevant products, scrapes reviews + Q&A, performs deep analysis (fake signals, temporal trends, competitive comparison), and outputs a rich Markdown report.

## Architecture

```
amazon-review-miner/
├── config.yaml              # User config (proxy, rate limits, output prefs)
├── cache/                   # SQLite cache — don't re-scrape same ASIN < 7 days
├── reports/                 # Generated .md reports land here
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI entry point
│   ├── config.py            # Config loader
│   ├── cache.py             # SQLite cache manager
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── amazon_search.py    # Search Amazon by product name → list of ASINs
│   │   ├── product_page.py     # Scrape product page: title, price, brand, variants, specs
│   │   ├── reviews.py          # Scrape reviews: paginated, all fields
│   │   ├── qa.py               # Scrape Q&A section
│   │   └── proxy.py            # Decodo residential proxy wrapper + rate limiter
│   ├── models/
│   │   ├── __init__.py
│   │   ├── product.py          # Product dataclass
│   │   ├── review.py           # Review dataclass
│   │   ├── qa.py               # Q&A dataclass
│   │   └── report.py           # Report dataclass (aggregated analysis)
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── temporal.py         # Temporal trend analysis
│   │   ├── fake_signals.py     # Fake review detection
│   │   ├── sentiment.py        # Sentiment extraction (pros/cons)
│   │   ├── comparison.py       # Competitive comparison engine
│   │   └── synthesis.py        # LLM synthesis → actionable summary
│   └── report_generator/
│       ├── __init__.py
│       └── markdown.py         # Rich .md report writer
├── tests/
│   ├── test_models.py
│   ├── test_scraper.py
│   ├── test_analysis.py
│   └── test_report.py
├── requirements.txt
├── pyproject.toml
├── README.md
└── CODER_BRIEF.md
```

## Data Models (Python dataclasses)

### Product
```python
@dataclass
class Product:
    asin: str
    title: str
    brand: str
    price: float | None          # Current price
    price_history: list[PricePoint]  # Optional: scraped price over time
    category: str                # Amazon category path
    url: str                     # https://www.amazon.com/dp/{ASIN}
    main_image_url: str | None
    variants: list[Variant]      # Different colors/sizes/flavors
    bullet_points: list[str]     # Key features from product page
    specs: dict[str, str]        # Product specifications table
    bs_rank: str | None          # Best Sellers Rank
    scraped_at: datetime
```

### Variant
```python
@dataclass
class Variant:
    asin: str
    name: str                    # e.g. "Blue, 32oz"
    price: float | None
    is_available: bool
```

### Review
```python
@dataclass
class Review:
    review_id: str
    asin: str
    rating: int                  # 1-5
    title: str
    body: str
    date: date
    verified_purchase: bool
    vine_voice: bool
    reviewer_id: str
    reviewer_rank: str | None    # e.g. "Top 1000 Reviewer"
    reviewer_total_reviews: int | None
    helpful_count: int
    images_count: int
    variant: str | None          # Which variant this review is for
    country: str                 # e.g. "US"
```

### QAEntry
```python
@dataclass
class QAEntry:
    question_id: str
    asin: str
    question: str
    answer: str
    answer_date: date | None
    vote_count: int
```

### TemporalTrend
```python
@dataclass
class TemporalTrend:
    asin: str
    monthly_data: list[MonthlyBucket]
    trend_direction: str         # "improving" | "declining" | "stable" | "mixed"
    recent_30d_avg: float        # Avg rating last 30 days
    recent_90d_avg: float        # Avg rating last 90 days
    overall_avg: float
    recent_30d_count: int        # Review count last 30 days
    anomaly_months: list[str]    # Months with unusual patterns
```

### MonthlyBucket
```python
@dataclass
class MonthlyBucket:
    year_month: str              # "2025-01"
    avg_rating: float
    review_count: int
    rating_distribution: dict[int, int]  # {1: count, 2: count, ...}
```

### FakeReviewSignals
```python
@dataclass
class FakeReviewSignals:
    asin: str
    vine_percentage: float       # % of reviews from Vine Voice
    unverified_percentage: float # % of non-verified purchase reviews
    burst_rate: float            # Max reviews/day in any 7-day window
    avg_reviewer_depth: float    # Average total reviews by reviewers
    one_review_account_pct: float # % of reviewers with 1 review only
    template_text_pct: float     # % of reviews with template-like text
    suspicious_timing: bool      # True if burst + low depth cluster
    overall_risk: str            # "low" | "medium" | "high"
    risk_score: float            # 0.0 (clean) to 1.0 (fabricated)
    signals: list[str]           # Human-readable list of flags raised
```

### CompetitiveComparison
```python
@dataclass
class CompetitiveComparison:
    primary_asin: str
    competitors: list[ComparedProduct]
    rating_winner: str
    value_winner: str            # Rating vs price
    cleanest_reviews_winner: str # Lowest fake risk
    recommendation: str          # LLM-generated: which to buy
```

### ComparedProduct
```python
@dataclass
class ComparedProduct:
    asin: str
    title: str
    price: float
    avg_rating: float
    review_count: int
    fake_risk_score: float
    recent_trend: str
    pros: list[str]              # Top 5 extracted pros
    cons: list[str]              # Top 5 extracted cons
```

### Report
```python
@dataclass
class Report:
    query: str                   # Original user query
    generated_at: datetime
    primary_product: Product
    review_summary: ReviewSummary
    temporal: TemporalTrend | None
    fake_signals: FakeReviewSignals | None
    qa_insights: list[str]       # Top Q&A takeaways
    pros: list[str]
    cons: list[str]
    sentiment_breakdown: dict
    competitive: CompetitiveComparison | None  # Only if multi-ASIN
    synthesis: str               # LLM-generated "should I buy this?"
    raw_data_path: str           # Path to saved JSON if user wants it
```

## Scraper Design

### Proxy Layer (`proxy.py`)
- Configured via `config.yaml` — Decodo residential proxy URL
- Rate limiter: enforce max N requests per hour (default: 3/hr as per user)
- Request queue with delay between queries
- Retry with backoff (3 attempts, 30s → 60s → 120s) on 503/blocked
- Rotate User-Agent on each request
- Log every HTTP request to `~/.amazon_miner/requests.log`

### Amazon Search (`amazon_search.py`)
- Given a product name, search Amazon and return top 10 ASINs
- Use `/?s=product+name` search URL pattern
- Extract ASIN from search result cards
- Return ordered list of ASINs + titles + prices

### Product Page (`product_page.py`)
- Scrape: title, brand, price, BS rank, category path, bullet points, specs table, main image
- Detect variant selector — list all variant ASINs with names and prices
- Return Product object

### Reviews (`reviews.py`)
- Scrape from `https://www.amazon.com/product-reviews/{ASIN}`
- Paginate through all available pages (stop if >2000 reviews or 50 pages)
- Extract every Review field defined above
- **IMPORTANT**: Rate limit — 1 request per page, minimum 60 seconds between pages
- Store raw HTML response hashes for dedup

### Q&A (`qa.py`)
- Scrape from `https://www.amazon.com/ask/questions/asin/{ASIN}`
- Paginate up to 5 pages
- Extract question, answer, date, vote count

## Analysis Engine

### Temporal Analysis (`temporal.py`)
- Bucket reviews by month
- Compute: avg rating, count, distribution per month
- Detect trend using linear regression on monthly averages
- Flag anomaly months (sudden spike or drop)
- Identify "recent quality decline" pattern (last 90 days significantly below overall avg)

### Fake Review Detection (`fake_signals.py`)
Rules-based scoring system (no external API needed):

| Signal | Weight | Threshold |
|---|---|---|
| Vine Voice % > 30% | 0.15 | High Vine = incentivized bias |
| Unverified % > 25% | 0.15 | Unverified = no purchase proof |
| Burst rate > 10 reviews/day | 0.20 | Unnatural spike |
| Avg reviewer depth < 5 | 0.15 | Inexperienced reviewers |
| One-review accounts > 20% | 0.15 | Sock puppet indicator |
| Template text (cosine sim clusters) | 0.20 | Same phrasing clusters |

Also flag:
- Reviews all on similar dates (batch posting)
- All 5★ or all 1★ reviews clumped in time
- Reviewer names with random character patterns
- Same reviewer posting for multiple products in same category

### Sentiment Extraction (`sentiment.py`)
- Extract pros and cons from review text using keyword/pattern matching initially
- LLM-enhanced extraction for the final synthesis
- Build frequency-ranked word clouds per rating level

### Competitive Comparison (`comparison.py`)
- If user provided a product name (not an ASIN URL), auto-discover top 5 competitors from search results
- If user provided a URL, treat that product as primary — optionally ask if they want to compare
- Compare: rating, price, fake risk, recent trend, review count
- Extract top pros/cons per product
- Determine value winner (rating/price ratio)

### LLM Synthesis (`synthesis.py`)
- Use an LLM call (configurable model) to generate the "Should I buy this?" section
- Feed: all analysis data as structured JSON
- Instruct LLM to produce:
  - Honest summary of pros and cons
  - Which variant to choose
  - What to check on arrival
  - Whether price is fair for the category
  - Any red flags (fake reviews, quality decline)
- Output must be grounded in data — no hallucinated claims

## Report Generator (`markdown.py`)

Generate a rich .md file with:

```markdown
# Amazon Review Report: [Product Title]

**Generated:** [date] | **Query:** [user input]

---

## 🏆 Verdict

[LLM synthesis paragraph — should I buy this?]

---

## 📊 Quick Stats

| Metric | Value |
|---|---|
| Price | $XX.XX |
| Avg Rating | ⭐ X.X (N reviews) |
| Recent 30d Trend | ↓ Improving / → Stable / ↑ Declining |
| Fake Review Risk | 🟢 Low / 🟡 Medium / 🔴 High |
| BSR | #XX in Category |

---

## 📈 Rating Over Time

[Plot or table showing monthly averages]

---

## 👍 Pros & 👎 Cons

### What People Love
1. [Pro] — mentioned in X% of reviews
2. [Pro] — mentioned in X% of reviews
...

### What People Complain About
1. [Con] — mentioned in X% of reviews
2. [Con] — mentioned in X% of reviews
...

---

## 🔍 Fake Review Analysis

- X% Vine Voice reviews
- X% unverified purchases
- Y burst days detected (max Z reviews/day)
- Risk assessment: Low/Medium/High

---

## 🗣️ Key Q&A Insights

- [Notable Q&A items]

---

## 🏅 Competitive Comparison (if applicable)

| Product | Price | Rating | Reviews | Fake Risk | Trend |
|---|---|---|---|---|---|
| [Primary] | $X | ⭐X.X | N | 🟢 | ↑ |
| Competitor 1 | $X | ⭐X.X | N | 🟡 | → |
| Competitor 2 | $X | ⭐X.X | N | 🔴 | ↓ |

**Best rated:** Product A
**Best value:** Product B
**Cleanest reviews:** Product C

---

## ⚠️ Red Flags & Caveats

- [List of specific warnings]

---

## 💡 Recommendation

[LLM final recommendation]

---

*Data sources: Amazon.com reviews, Q&A, product page*
*Rate: Scraped at [rate] queries/hour*
```

## Config (`config.yaml`)

```yaml
# Amazon Review Miner Configuration

proxy:
  provider: decodo           # Residential proxy provider
  url: ""                    # Proxy URL / gateway endpoint
  rotate_ip: true            # Rotate IP per request

rate_limits:
  queries_per_hour: 3        # Max search+scrape cycles per hour
  seconds_between_pages: 60  # Delay between review page requests
  max_retries: 3
  retry_backoff_base: 30     # Seconds

scraping:
  max_reviews: 2000          # Max reviews to scrape per ASIN
  max_qa_pages: 5
  cache_days: 7              # Don't re-scrape same ASIN within N days
  user_agents:               # Rotate through these
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ..."
    - "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ..."
    - "Mozilla/5.0 (X11; Linux x86_64) ..."

llm:
  model: "deepseek-v4-flash"  # Model for synthesis
  provider: "deepseek"
  max_tokens: 2000

output:
  format: "markdown"
  report_dir: "./reports/"
  keep_raw_data: true         # Save raw JSON alongside .md

storage:
  cache_db: "./cache/reviews.db"  # SQLite cache
```

## Caching (`cache.py`)

- SQLite database at path from config
- Tables: `products`, `reviews`, `qa`, `report_cache`
- Before scraping: check if ASIN has been scraped within `cache_days`
- Cache keyed by ASIN + scrape_date (YYYY-MM-DD)
- Old cache entries auto-evicted after 30 days

## CLI (`cli.py`)

```
usage: amazon-review-miner [-h] [--config CONFIG] [--compare] [--output-dir DIR]
                           [--no-cache] [--quiet]
                           query

Amazon Review Miner — Deep review analysis tool

positional arguments:
  query              Product name or Amazon URL

options:
  -h, --help         Show help
  --config CONFIG    Path to config file (default: ./config.yaml)
  --compare          Enable competitive comparison (auto-find competitors)
  --output-dir DIR   Output directory for reports (default: ./reports/)
  --no-cache         Bypass cache, force fresh scrape
  --quiet            Suppress progress output
```

Flow:
1. Parse input — detect if URL or product name
2. If product name: call `amazon_search` → pick primary ASIN
3. If URL: extract ASIN from URL
4. If `--compare`: find top competitors from search results
5. Check cache → skip if fresh
6. Scrape product page → reviews → Q&A (rate-limited)
7. Run analysis pipeline
8. If multi-ASIN, run competitive comparison
9. Generate LLM synthesis
10. Write .md report + raw JSON
11. Print report path to stdout

## Dependencies (use these exact versions or latest compatible)

```
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.1.0
httpx>=0.27.0           # Async HTTP (for parallel page fetches where rate limit allows)
python-dateutil>=2.8.0
pydantic>=2.0.0          # For config validation
rich>=13.0.0             # CLI progress display
scipy>=1.11.0            # Linear regression for temporal trends
numpy>=1.24.0
```

## Constraints & Rules

1. **NO aggressive scraping** — the user explicitly said "a couple of queries per hour." The rate limiter must be strict and configurable.
2. **Decodo residential proxy** — all HTTP requests go through the proxy configured in config.yaml. No direct Amazon connections.
3. **LLM calls are optional** — the tool must produce a useful report even without LLM synthesis (fallback to pattern-based pros/cons extraction). The LLM is an enhancement for the "Verdict" section only.
4. **Cache aggressively** — don't re-scrape what we already have. Check cache before every scrape.
5. **Graceful degradation** — if product page scrapes but reviews fail, produce a partial report. If all scraping fails, report the error clearly.
6. **No .env, no hardcoded secrets** — all config in config.yaml. Proxy credentials in config (or user provides them on first run).
7. **The report .md file is the primary output** — it must be beautiful, informative, and self-contained. Assume the user will read it, share it, and action it.

## Testing Expectations

- Unit tests for all model dataclasses
- Unit tests for analysis functions (temporal, fake signals, sentiment)
- Integration test for CLI flow (mocked HTTP)
- Test cache logic (fresh vs stale, eviction)
- Test proxy wrapper
- Test report markdown generation

## Build Order (Chunks for Sequential Delegation)

Will be routed to Coder in 4 chunks:

**Chunk 1** — Foundation: data models, config loader, cache, proxy layer, CLI skeleton
**Chunk 2** — Scrapers: amazon_search, product_page, reviews, qa
**Chunk 3** — Analysis: temporal, fake_signals, sentiment, comparison, synthesis
**Chunk 4** — Output: report generator, final CLI wiring, tests, README
