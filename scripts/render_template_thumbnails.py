#!/usr/bin/env python3
"""Pre-warm the Video 3D card thumbnails of a running HocusPocus, one card at a time.

Every shipped and stage card's ``preview`` is the URL of our own render
(``GET /api/v1/world3d/templates/<id>/thumbnail``), painted on demand and cached
once per template version. This asks a server for every card's picture in turn
so later requests are cache hits, and reports the time of each one and every
failure. Not part of CI; it renders on that server's GPU.

    python scripts/render_template_thumbnails.py --url http://127.0.0.1:42017
    python scripts/render_template_thumbnails.py --url http://127.0.0.1:42017 --kind stage
    python scripts/render_template_thumbnails.py --url http://127.0.0.1:42017 --only two-shot,stage-bar

The live instances (42003, 42042) are refused unless ``--allow-live``: a render
there takes the GPU from the work running on them. A 503 ``thumbnail_unavailable``
(the GPU is busy, another picture is rendering) is retried ``--retries`` times.
Exit status: 0 when every picture was served, 1 when any failed, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

LIVE_PORTS = frozenset({42003, 42042})
COMMANDS = "/api/v1/world3d/templates/commands"
PAGE = 50


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and cache every Video 3D card thumbnail of a running server.")
    parser.add_argument("--url", required=True, help="the server, e.g. http://127.0.0.1:42017")
    parser.add_argument("--only", default="", help="comma-separated card ids; the rest are skipped")
    parser.add_argument("--kind", default=None, help="only cards of this kind (scene, stage, camera, look, transition, title)")
    parser.add_argument("--workspace", default="default", help="the workspace the card list is read in (default: default)")
    parser.add_argument("--retries", type=int, default=2, help="retries of a retryable 503 per card (default 2)")
    parser.add_argument("--pause", type=float, default=5.0, help="seconds before a retry (default 5)")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds one request may take (default 300)")
    parser.add_argument("--report", default=None, help="write the per-card results as JSON to this file")
    parser.add_argument("--allow-live", action="store_true", help="allow the live ports 42003 and 42042")
    return parser.parse_args(argv)


def check_target(url: str, allow_live: bool) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"--url must be http(s)://host:port, not {url!r}")
    if parts.port in LIVE_PORTS and not allow_live:
        raise ValueError(f"port {parts.port} is a live instance; pre-warm an isolated one or pass --allow-live")
    return url.rstrip("/")


def _post(base: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(base + COMMANDS, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def list_cards(base: str, *, workspace: str, kind: str | None, timeout: float) -> list[dict]:
    """Every card of the library in id order (``world3d.templates.list`` without a query pages by id)."""
    cards: list[dict] = []
    offset = 0
    while True:
        data = {"workspace": workspace, "limit": PAGE, "offset": offset, **({"kind": kind} if kind else {})}
        page = _post(base, {"operation": "world3d.templates.list", "version": 1, "input": data}, timeout)["result"]
        cards.extend(page["templates"])
        offset += PAGE
        if offset >= int(page.get("total") or 0) or not page["templates"]:
            return cards


def _error_detail(error: urllib.error.HTTPError) -> dict:
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (ValueError, OSError):
        return {}
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, dict) else {}


def fetch(base: str, path: str, *, retries: int, pause: float, timeout: float) -> dict:
    """One card's picture: ``{status, cache, bytes, seconds, attempts}`` or a failure with its code and reason."""
    started = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as response:
                data = response.read()
                return {"status": "ok", "cache": response.headers.get("X-Thumbnail-Cache") or "unknown",
                        "type": response.headers.get("Content-Type"), "bytes": len(data),
                        "seconds": round(time.monotonic() - started, 2), "attempts": attempts}
        except urllib.error.HTTPError as error:
            detail = _error_detail(error)
            if error.code == 503 and detail.get("retryable") and attempts <= retries:
                time.sleep(pause)
                continue
            return {"status": "failed", "http": error.code, "code": detail.get("code"), "reason": detail.get("reason"),
                    "message": str(detail.get("message") or error.reason)[:300],
                    "seconds": round(time.monotonic() - started, 2), "attempts": attempts}
        except (urllib.error.URLError, OSError) as error:
            return {"status": "failed", "http": None, "code": "unreachable", "reason": None, "message": str(error)[:300],
                    "seconds": round(time.monotonic() - started, 2), "attempts": attempts}


def _line(index: int, total: int, card_id: str, result: dict) -> str:
    width = len(str(total))
    head = f"[{index:>{width}}/{total}]"
    if result["status"] == "ok":
        kind = {"hit": "cached", "miss": "rendered"}.get(result["cache"], result["cache"])
        return f"{head} ok    {kind:<8} {card_id}  {result['seconds']:.2f} s  {result['bytes'] // 1024} KB"
    why = "/".join(str(part) for part in (result.get("http"), result.get("code"), result.get("reason")) if part)
    return f"{head} FAIL  {card_id}  {why}: {result['message']}"


def summary(results: dict[str, dict], seconds: float) -> list[str]:
    ok = {key: value for key, value in results.items() if value["status"] == "ok"}
    rendered = sum(1 for value in ok.values() if value["cache"] == "miss")
    failed = sorted(key for key, value in results.items() if value["status"] != "ok")
    lines = [f"{len(results)} cards: {rendered} rendered, {len(ok) - rendered} cached, {len(failed)} failed in {seconds:.1f} s"]
    slowest = sorted(ok.items(), key=lambda item: -item[1]["seconds"])[:5]
    if slowest:
        lines.append("slowest: " + ", ".join(f"{key} {value['seconds']:.1f} s" for key, value in slowest))
    if failed:
        lines.append("failed: " + ", ".join(failed))
    return lines


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base = check_target(args.url, args.allow_live)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    only = list(dict.fromkeys(item.strip() for item in args.only.split(",") if item.strip()))
    started = time.monotonic()
    try:
        cards = list_cards(base, workspace=args.workspace, kind=args.kind, timeout=args.timeout)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        print(f"error: could not list the cards at {base}: {error}", file=sys.stderr)
        return 1
    # Personal templates have no picture (preview null); they are not counted.
    listed = {card["id"]: card["preview"] for card in cards if card.get("preview")}
    order = only or list(listed)
    results: dict[str, dict] = {}
    for index, card_id in enumerate(order, start=1):
        if card_id in listed:
            results[card_id] = fetch(base, listed[card_id], retries=max(0, args.retries), pause=max(0.0, args.pause),
                                     timeout=args.timeout)
        else:
            results[card_id] = {"status": "failed", "http": None, "code": "not_listed", "reason": None, "seconds": 0,
                                "attempts": 0, "message": "not in the card list: an unknown id, a personal template "
                                                          "or another --kind"}
        print(_line(index, len(order), card_id, results[card_id]), flush=True)
    for line in summary(results, time.monotonic() - started):
        print(line)
    if args.report:
        Path(args.report).write_text(json.dumps({"url": base, "results": results}, indent=2), encoding="utf-8")
    return 1 if any(value["status"] != "ok" for value in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
