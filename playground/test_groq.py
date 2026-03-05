#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple Groq API connectivity test")
    parser.add_argument("--model", default="openai/gpt-oss-120b", help="Groq model id")
    parser.add_argument("--prompt", default="Reply with exactly: OK", help="Prompt text")
    parser.add_argument("--base-url", default=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    parser.add_argument("--api-key", default=os.getenv("GROQ_API_KEY", ""))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--ca-bundle",
        default=os.getenv("SSL_CERT_FILE", ""),
        help="Path to CA bundle PEM file (optional)",
    )
    parser.add_argument("--insecure", action="store_true", help="Disable TLS cert verification")
    parser.add_argument("--list-models", action="store_true", help="List models available to this API key")
    return parser.parse_args()


def build_ssl_context(ca_bundle: str, insecure: bool) -> ssl.SSLContext:
    if insecure:
        return ssl._create_unverified_context()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    return ssl.create_default_context()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("Missing GROQ_API_KEY (or pass --api-key).", file=sys.stderr)
        return 2

    if args.list_models:
        url = f"{args.base_url.rstrip('/')}/models"
        data = None
        method = "GET"
    else:
        url = f"{args.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": args.prompt}],
            "stream": False,
            "temperature": 0,
            "top_p": 1,
            "max_completion_tokens": 128,
        }
        data = json.dumps(payload).encode("utf-8")
        method = "POST"
    headers = {
        "Authorization": f"Bearer {args.api_key}",
    }
    if not args.list_models:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    context = build_ssl_context(args.ca_bundle, args.insecure)

    print(f"{method} {url}")
    if not args.list_models:
        print(f"model={args.model}")
    if args.insecure:
        print("tls_verify=disabled")
    elif args.ca_bundle:
        print(f"tls_verify=custom_ca:{args.ca_bundle}")
    else:
        print("tls_verify=system_default")

    try:
        with urllib.request.urlopen(request, timeout=args.timeout, context=context) as response:
            print(f"status={response.status}")
            print(f"server={response.headers.get('server', '')}")
            print(f"content-type={response.headers.get('content-type', '')}")
            raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTPError: status={exc.code}", file=sys.stderr)
        print(f"server={exc.headers.get('server', '')}", file=sys.stderr)
        print(f"content-type={exc.headers.get('content-type', '')}", file=sys.stderr)
        try:
            parsed = json.loads(body)
            print(json.dumps(parsed, ensure_ascii=False, indent=2)[:2000], file=sys.stderr)
        except Exception:
            print(body[:2000], file=sys.stderr)
        return 1
    except ssl.SSLError as exc:
        print(f"SSLError: {exc}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"URLError: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    if args.list_models:
        models = payload.get("data", [])
        if not isinstance(models, list):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        ids = [m.get("id", "") for m in models if isinstance(m, dict)]
        print(f"\nmodels={len(ids)}")
        for mid in sorted(x for x in ids if x):
            print(mid)
        return 0

    choices = payload.get("choices", [])
    if not choices:
        print("No choices in response:", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    message = choices[0].get("message", {}).get("content", "")
    print("\nResponse:")
    print(message if isinstance(message, str) else json.dumps(message, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
