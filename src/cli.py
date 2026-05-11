from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amazon Review Miner")
    parser.add_argument("query", help="Product name or Amazon URL")
    parser.add_argument("--config", default="./config.yaml")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Enable competitive comparison",
    )
    parser.add_argument("--output-dir", default="./reports/")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(f"Amazon Review Miner v0.1")
    print(f"Query: {args.query}")
    print(f"Config: {args.config}")
    # For now just prints args — actual pipeline comes later


if __name__ == "__main__":
    main()
