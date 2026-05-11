# 🕵️ Amazon Review Miner

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)

Deep Amazon review analysis tool — enter a product name or URL, get a rich Markdown report with fake review detection, temporal trends, competitive comparison, and LLM-powered synthesis.

## Features

- 🔍 **Product lookup** — search by name or paste a URL
- 📊 **Review scraping** — configurable rate limits, proxy support
- 🕵️ **Fake review detection** — 7 signals with weighted risk scoring
- 📈 **Temporal trend analysis** — is quality improving or declining?
- 🏅 **Competitive comparison** — compare up to 5 competing products
- 🤖 **LLM synthesis** — a "should I buy this?" verdict
- 📝 **Rich Markdown reports** — tables, emoji, actionable sections
- 💾 **SQLite cache** — don't re-scrape what you already have
- 🛡️ **Decodo residential proxy** support
- ⚙️ **Fully configurable** via YAML

## Installation

```bash
git clone https://github.com/Mdonci/Amazon-Review-Miner.git
cd Amazon-Review-Miner
pip install -r requirements.txt
```

## Configuration

Edit `config.yaml` to set:

- **Proxy URL** — your Decodo residential proxy endpoint
- **Rate limits** — queries per hour, delay between pages
- **LLM model** — for the synthesis verdict
- **Output preferences** — report directory, cache location

## Usage

```bash
# Search by product name
python3 src/cli.py "Vitamin D3 K2 drops"

# Paste an Amazon URL
python3 src/cli.py "https://www.amazon.com/dp/B0EXAMPLE"

# With competitive comparison (auto-finds competitors)
python3 src/cli.py "protein powder" --compare

# Bypass cache for fresh data
python3 src/cli.py "bluetooth speaker" --no-cache

# Custom output directory
python3 src/cli.py "mechanical keyboard" --output-dir ./my-reports/

# Quiet mode
python3 src/cli.py "noise cancelling headphones" --quiet
```

## Output

Reports are saved as Markdown (`.md`) files in `reports/` with:

| Section | Description |
|---------|-------------|
| 🏆 Verdict | LLM synthesis — should you buy this? |
| 📊 Quick Stats | Price, rating, trend, fake risk |
| 📈 Rating Over Time | Monthly averages with trend arrows |
| 👍 Pros & 👎 Cons | Keyword-extracted strengths and complaints |
| 🔍 Fake Review Analysis | All 7 signals + risk score |
| 🗣️ Q&A Insights | Notable customer questions |
| 🏅 Competitive Comparison | Multi-product comparison table |
| ⚠️ Red Flags | Quality changes, suspicious patterns |
| 💡 Recommendation | Which variant/competitor to choose |

## Architecture

```
src/
├── models/              # Dataclass data models
├── scraper/             # Amazon scrapers (search, product, reviews, Q&A)
├── analysis/            # Analysis engine (temporal, fake signals, sentiment, comparison, synthesis)
├── report_generator/    # Markdown report writer
├── cache.py             # SQLite cache manager
├── config.py            # YAML config loader
├── cli.py               # CLI entry point + pipeline orchestration
```

## Disclaimer

This tool is for research purposes. Respect Amazon's Terms of Service and `robots.txt`. Use responsibly with conservative rate limits.
