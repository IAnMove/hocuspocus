"""Submit/replay a native generation command and retain evidence of completion."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

from native import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    command = json.loads(args.command.read_text(encoding="utf-8"))
    receipt = request(args.base_url, "/api/v1/generation/commands", command, timeout=300)
    task_id = receipt["receipt"]["taskIds"][0]
    workspace = command["input"]["workspace"]
    evidence = {"command": command, "receipt": receipt}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        task = request(args.base_url, "/api/v1/tasks/" + quote(task_id) + "?workspace=" + quote(workspace))["task"]
        evidence["task"] = task
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        if task["status"] in ("completed", "failed", "cancelled"):
            print(json.dumps({"status": task["status"], "task": task_id,
                              "files": task.get("result_refs"), "error": task.get("error")}), flush=True)
            if task["status"] != "completed":
                raise SystemExit(1)
            return
        time.sleep(3)
    raise TimeoutError("Task still pending; rerun the identical command to resume polling")


if __name__ == "__main__":
    main()
