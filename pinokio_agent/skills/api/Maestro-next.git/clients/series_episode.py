#!/usr/bin/env python3
"""Small cross-platform client for Maestro Series Lab episode workflows."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def request(base_url: str, path: str, method: str = "GET", payload: dict | None = None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Maestro: {exc.reason}") from exc
    return json.loads(raw) if raw else None


def episode_path(series_id: str, episode_id: str) -> str:
    return f"/api/v1/series/{quote(series_id)}/episodes/{quote(episode_id)}"


def add_common_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--episode-id", required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace", default="default")
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project")
    project.add_argument("--series-id", required=True)

    episode = commands.add_parser("episode")
    add_common_target(episode)

    set_status = commands.add_parser("set-status")
    add_common_target(set_status)
    set_status.add_argument(
        "--status",
        required=True,
        choices=("draft", "outline", "script", "shot_plan", "rendering", "completed", "archived"),
    )

    prepare = commands.add_parser("prepare-from-job")
    add_common_target(prepare)
    prepare.add_argument("--source-job-id", required=True)
    prepare.add_argument("--duration", type=int, required=True)

    start_plan = commands.add_parser("start-plan")
    add_common_target(start_plan)
    start_plan.add_argument("--scope", choices=("outline", "script", "shots", "complete"), default="shots")
    start_plan.add_argument("--instruction", default="")

    plan_status = commands.add_parser("plan-status")
    plan_status.add_argument("--job-id", required=True)

    apply_plan = commands.add_parser("apply-plan")
    apply_plan.add_argument("--job-id", required=True)

    start_render = commands.add_parser("start-render")
    add_common_target(start_render)
    start_render.add_argument("--mode", choices=("selected", "failed", "missing", "all"), default="missing")
    start_render.add_argument("--shot-id", action="append", default=[])
    start_render.add_argument("--seed", type=int)

    render_status = commands.add_parser("render-status")
    render_status.add_argument("--job-id", required=True)

    cancel_render = commands.add_parser("cancel-render")
    cancel_render.add_argument("--job-id", required=True)

    resume_render = commands.add_parser("resume-render")
    resume_render.add_argument("--job-id", required=True)

    args = parser.parse_args()
    base = args.base_url
    workspace_query = urlencode({"workspace": args.workspace})

    if args.command == "project":
        result = request(base, f"/api/v1/series/{quote(args.series_id)}?{workspace_query}")
    elif args.command == "episode":
        result = request(base, f"{episode_path(args.series_id, args.episode_id)}?{workspace_query}")
    elif args.command == "set-status":
        current = request(base, f"{episode_path(args.series_id, args.episode_id)}?{workspace_query}")
        updated = dict(current)
        updated["status"] = args.status
        result = request(
            base,
            episode_path(args.series_id, args.episode_id),
            "PUT",
            {"workspace": args.workspace, "episode": updated},
        )
    elif args.command == "prepare-from-job":
        current = request(base, f"{episode_path(args.series_id, args.episode_id)}?{workspace_query}")
        source = request(base, f"/api/v1/series/plan/jobs/{quote(args.source_job_id)}")
        completed = source.get("completedStages") if isinstance(source, dict) else {}
        if not isinstance(completed, dict) or not isinstance(completed.get("script"), dict):
            raise RuntimeError("The source planning job has no recoverable script stage")
        updated = dict(current)
        if isinstance(completed.get("outline"), dict):
            updated["outline"] = completed["outline"].get("outline", updated.get("outline"))
        updated["script"] = completed["script"].get("script", [])
        updated["targetDurationSeconds"] = max(15, min(3600, args.duration))
        updated["shots"] = []
        updated["status"] = "script"
        result = request(
            base,
            episode_path(args.series_id, args.episode_id),
            "PUT",
            {"workspace": args.workspace, "episode": updated},
        )
    elif args.command == "start-plan":
        result = request(
            base,
            f"{episode_path(args.series_id, args.episode_id)}/plan/start",
            "POST",
            {"workspace": args.workspace, "scope": args.scope, "instruction": args.instruction},
        )
    elif args.command == "plan-status":
        result = request(base, f"/api/v1/series/plan/jobs/{quote(args.job_id)}")
    elif args.command == "apply-plan":
        result = request(base, f"/api/v1/series/plan/jobs/{quote(args.job_id)}/apply", "POST", {})
    elif args.command == "start-render":
        payload = {"workspace": args.workspace, "mode": args.mode}
        if args.shot_id:
            payload["shotIds"] = args.shot_id
        if args.seed is not None:
            payload["seed"] = args.seed
        result = request(
            base,
            f"{episode_path(args.series_id, args.episode_id)}/render/start",
            "POST",
            payload,
        )
    elif args.command == "render-status":
        result = request(base, f"/api/v1/series/render/jobs/{quote(args.job_id)}")
    elif args.command == "cancel-render":
        result = request(
            base, f"/api/v1/series/render/jobs/{quote(args.job_id)}/cancel", "POST", {},
        )
    else:
        result = request(
            base, f"/api/v1/series/render/jobs/{quote(args.job_id)}/resume", "POST", {},
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
