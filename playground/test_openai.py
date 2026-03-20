#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Simple OpenAI API connectivity test")
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI model id")
    parser.add_argument("--prompt", default="Reply with exactly: OK", help="Prompt text")
    parser.add_argument(
        "--env-file",
        default=str(root / "backend" / ".env"),
        help="Path to .env file that contains OPENAI_API_KEY",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    return parser.parse_args()


def normalize_base_url(raw_base_url: str) -> str:
    base_url = raw_base_url.strip().rstrip("/")
    if not base_url:
        return ""
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        print(
            "Missing dependency: python-dotenv. Install with: "
            "backend/.venv/bin/pip install python-dotenv",
            file=sys.stderr,
        )
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "Missing dependency: openai. Install with: "
            "backend/.venv/bin/pip install openai",
            file=sys.stderr,
        )
        return 2

    args = parse_args()
    env_file = Path(args.env_file)
    load_dotenv(env_file, override=False)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(f"Missing OPENAI_API_KEY in {env_file}", file=sys.stderr)
        return 2

    client_kwargs = {"api_key": api_key, "timeout": args.timeout}
    base_url = normalize_base_url(os.getenv("OPENAI_BASE_URL", ""))
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)

    try:
        response = client.responses.create(
            model=args.model,
            input=args.prompt,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"OpenAI request failed: {exc}", file=sys.stderr)
        return 1

    text = (response.output_text or "").strip()
    if not text:
        print("No text output in response.", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
