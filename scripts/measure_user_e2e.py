"""User-facing E2E latency: typed ask → answer received (gateway /copilot/query).

Wall-clock from HTTP request start until response body is fully read —
what the cockpit user waits for on a text query (includes intent + Core AI + TTS).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_QUERY = "What is the HVAC system?"


def _call(base: str, query: str, language: str, bypass: bool, timeout_s: float) -> dict:
    url = base.rstrip("/") + "/api/v1/copilot/query"
    body = json.dumps({"query": query, "language": language}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bypass:
        headers["X-Cache-Bypass"] = "1"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
        hdrs = {k: v for k, v in resp.headers.items()}
        status = resp.status
    wall_ms = (time.perf_counter() - t0) * 1000.0
    payload = json.loads(raw.decode("utf-8"))
    lat = payload.get("latency") or {}
    return {
        "wall_ms": wall_ms,
        "http_status": status,
        "answer_status": payload.get("status"),
        "answer_chars": len(payload.get("answer") or ""),
        "has_audio": bool(payload.get("audio_base64")),
        "cache": hdrs.get("X-Cache-Status") or hdrs.get("x-cache-status"),
        "hdr_total": hdrs.get("X-Latency-Total-Ms") or hdrs.get("x-latency-total-ms"),
        "hdr_core": hdrs.get("X-Latency-Core-AI-Ms") or hdrs.get("x-latency-core-ai-ms"),
        "hdr_tts": hdrs.get("X-Latency-TTS-Ms") or hdrs.get("x-latency-tts-ms"),
        "hdr_intent": hdrs.get("X-Latency-Intent-Ms") or hdrs.get("x-latency-intent-ms"),
        "json_total": lat.get("total_ms"),
        "json_core": lat.get("core_ai_ms"),
        "json_tts": lat.get("tts_ms"),
    }


def _pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    if not s:
        return 0.0
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--language", default="en", choices=["vi", "en"])
    ap.add_argument("--n", type=int, default=5, help="Warm samples after first (user) query")
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--no-bypass", action="store_true", help="Allow gateway cache on warm runs")
    args = ap.parse_args()

    bypass = not args.no_bypass

    # Health
    try:
        with urllib.request.urlopen(args.base_url.rstrip("/") + "/api/v1/health", timeout=5) as r:
            if r.status != 200:
                raise RuntimeError(r.status)
    except Exception as exc:
        print(f"error: gateway not healthy at {args.base_url}: {exc}", file=sys.stderr)
        return 2

    print("## User-facing E2E latency (typed ask → answer received)")
    print()
    print(f"- path: `POST {args.base_url}/api/v1/copilot/query`")
    print(f"- query: `{args.query}`")
    print(f"- language: `{args.language}`")
    print(f"- cache_bypass: `{bypass}`")
    print("- metric: client wall-clock until full JSON body received")
    print()

    # First user query (cold-ish for this session path)
    try:
        first = _call(args.base_url, args.query, args.language, bypass=True, timeout_s=args.timeout_s)
    except urllib.error.URLError as exc:
        print(f"error: first query failed: {exc}", file=sys.stderr)
        return 2

    print("| Phase | wall_ms | X-Latency-Total | core_ms | tts_ms | intent_ms | cache | status | audio |")
    print("|-------|---------|-----------------|---------|--------|-----------|-------|--------|-------|")
    print(
        f"| first_user_query | {first['wall_ms']:.0f} | {first['hdr_total']} | "
        f"{first['hdr_core']} | {first['hdr_tts']} | {first['hdr_intent']} | "
        f"{first['cache']} | {first['answer_status']} | {first['has_audio']} |"
    )

    warm: list[dict] = []
    for _ in range(max(0, args.n)):
        warm.append(
            _call(args.base_url, args.query, args.language, bypass=bypass, timeout_s=args.timeout_s)
        )

    if warm:
        walls = [w["wall_ms"] for w in warm]
        last = warm[-1]
        print(
            f"| warm_p50 (n={len(warm)}) | {_pct(walls, 50):.0f} | — | — | — | — | "
            f"{last['cache']} | {last['answer_status']} | {last['has_audio']} |"
        )
        print(
            f"| warm_p95 (n={len(warm)}) | {_pct(walls, 95):.0f} | — | — | — | — | "
            f"{last['cache']} | {last['answer_status']} | {last['has_audio']} |"
        )
        print(
            f"| warm_avg (n={len(warm)}) | {statistics.fmean(walls):.0f} | "
            f"{last['hdr_total']} | {last['hdr_core']} | {last['hdr_tts']} | "
            f"{last['hdr_intent']} | {last['cache']} | {last['answer_status']} | "
            f"{last['has_audio']} |"
        )

    print()
    print(
        "> `wall_ms` = user wait time. Headers break down gateway stages. "
        "TTS may dominate if Gemini/edge-tts is enabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
