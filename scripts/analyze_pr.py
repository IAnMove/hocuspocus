"""PR review agent for Loreframe Studio.

Reads a unified diff (or computes one from git) and writes a structured
review: risk, findings, area ownership, and the CONTRIBUTING.md checklist.

No network, no LLM, no third-party packages. Safe to run in GitHub Actions
or locally before opening a PR.

Usage:
    python scripts/analyze_pr.py --base origin/main
    python scripts/analyze_pr.py --diff /tmp/pr.diff --out /tmp/review.md
    python scripts/analyze_pr.py --diff -   # read stdin
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

COMMENT_MARKER = "<!-- loreframe-pr-review -->"

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

WEIGHT_EXTENSIONS = (
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
    ".onnx",
    ".engine",
)

NEVER_PUBLISH = [
    (re.compile(r"(^|/)_supplement_pack/"),
     "supplement pack (must stay gitignored)"),
    (re.compile(r"(^|/)app/postprocessing/seedvc/"),
     "seed-vc (GPL-3.0, fetched at install — do not vendor)"),
    (re.compile(r"(^|/)finetunes/[^/]*\.json$"),
     "finetune JSON (per-checkpoint guide — must stay gitignored)"),
    (re.compile(r"\.guide\.md$"),
     "generated per-LoRA guide (must stay gitignored)"),
    (re.compile(r"\.civitai\.json$"),
     "CivitAI metadata sidecar (must stay gitignored)"),
]

SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|private[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}"),
     "possible hardcoded credential"),
    (re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
     "private key material"),
    (re.compile(r"(?i)(sk-|ghp_|gho_|github_pat_|hf_)[A-Za-z0-9_\-]{16,}"),
     "token-shaped secret"),
]

TELEMETRY_PATTERNS = [
    (re.compile(r"(?i)\b(telemetry|phone[-_ ]?home|analytics\.track|sentry\.init|posthog)\b"),
     "possible telemetry / phone-home"),
]

DANGEROUS_CODE = [
    (re.compile(r"\beval\s*\("), "eval()"),
    (re.compile(r"\bexec\s*\("), "exec()"),
    (re.compile(r"pickle\.loads?\s*\("), "pickle.load/loads"),
    (re.compile(r"subprocess\.[A-Za-z_]+\([^)\n]*shell\s*=\s*True"),
     "subprocess(..., shell=True)"),
]

AREA_OWNERS = (
    ("app/services/", "backend services"),
    ("app/launch.py", "API launcher"),
    ("app/wgp.py", "generation pipeline"),
    ("ui/src/", "React UI"),
    ("scripts/", "repo scripts / CI"),
    (".github/", "GitHub workflows"),
    ("docs/", "docs"),
    ("app/recipes/", "bundled recipes"),
    ("pinokio.js", "Pinokio launcher"),
    ("install.js", "Pinokio installer"),
    ("start.js", "Pinokio start"),
    ("update.js", "Pinokio updater"),
)


@dataclass
class FileDiff:
    path: str
    status: str  # added, modified, deleted, renamed
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    new_path: str | None = None

    @property
    def effective_path(self) -> str:
        return self.new_path or self.path


@dataclass
class Finding:
    severity: str
    title: str
    detail: str
    path: str | None = None


@dataclass
class Review:
    files: list[FileDiff]
    findings: list[Finding]
    areas: list[str]
    added_lines: int
    removed_lines: int

    @property
    def risk(self) -> str:
        if any(f.severity == "high" for f in self.findings):
            return "high"
        if any(f.severity == "medium" for f in self.findings):
            return "medium"
        if self.files:
            return "low"
        return "low"


def parse_unified_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_path = ""
    new_path = ""

    for line in text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current)
            current = None
            old_path = ""
            new_path = ""
            continue
        if line.startswith("rename from "):
            old_path = line[len("rename from "):].strip()
            continue
        if line.startswith("rename to "):
            new_path = line[len("rename to "):].strip()
            continue
        if line.startswith("--- "):
            raw = line[4:].strip()
            if raw != "/dev/null":
                old_path = raw[2:] if raw.startswith("a/") else raw
            continue
        if line.startswith("+++ "):
            raw = line[4:].strip()
            status = "modified"
            if raw == "/dev/null":
                status = "deleted"
                path = old_path
                dest = None
            else:
                path = raw[2:] if raw.startswith("b/") else raw
                dest = None
                if old_path and old_path != path:
                    status = "renamed"
                    dest = path
                    path = old_path
                elif not old_path:
                    status = "added"
            current = FileDiff(path=path, status=status, new_path=dest)
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append(line[1:])

    if current is not None:
        files.append(current)
    return files


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _is_test_path(path: str) -> bool:
    norm = _norm(path)
    return (
        norm.startswith("tests/")
        or "/__tests__/" in norm
        or norm.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def _is_doc_path(path: str) -> bool:
    norm = _norm(path).lower()
    return (
        norm.endswith((".md", ".txt"))
        or norm.startswith("docs/")
        or norm in {"changelog.md", "license", "version"}
    )


def _needs_python_tests(path: str) -> bool:
    norm = _norm(path)
    if not norm.endswith(".py"):
        return False
    if _is_test_path(norm):
        return False
    return (
        norm.startswith("app/services/")
        or norm in {"app/launch.py"}
        or norm.startswith("scripts/")
    )


def analyze_files(files: Iterable[FileDiff]) -> Review:
    files = list(files)
    findings: list[Finding] = []
    areas: set[str] = set()
    added_lines = 0
    removed_lines = 0
    has_python_product_change = False
    has_test_change = False
    has_ui_change = False

    for fd in files:
        path = _norm(fd.effective_path)
        added_lines += len(fd.added)
        removed_lines += len(fd.removed)

        if _is_test_path(path):
            has_test_change = True
        if path.startswith("ui/"):
            has_ui_change = True
        if _needs_python_tests(path) and fd.status != "deleted":
            has_python_product_change = True

        for prefix, label in AREA_OWNERS:
            if path == prefix or path.startswith(prefix):
                areas.add(label)
                break

        if fd.status == "deleted":
            continue

        for pat, label in NEVER_PUBLISH:
            if pat.search(path):
                findings.append(Finding(
                    "high",
                    "Never-publish artifact in the diff",
                    f"`{path}` matches a clean-repo boundary: {label}.",
                    path,
                ))

        lower = path.lower()
        if lower.endswith(WEIGHT_EXTENSIONS) or "/ckpts/" in lower:
            findings.append(Finding(
                "high",
                "Model weight or checkpoint committed",
                f"`{path}` looks like a downloaded weight. Keep checkpoints gitignored.",
                path,
            ))

        # The detector and its fixture tests embed the needles on purpose.
        if path in {"scripts/analyze_pr.py", "tests/test_analyze_pr.py"}:
            continue

        joined = "\n".join(fd.added)
        if not _is_test_path(path) and not _is_doc_path(path):
            for pat, label in SECRET_PATTERNS:
                if pat.search(joined):
                    findings.append(Finding(
                        "high",
                        "Possible secret in added lines",
                        f"`{path}`: {label}. Remove it and rotate the credential.",
                        path,
                    ))
                    break

        if path.endswith((".py", ".js", ".ts", ".tsx")):
            for pat, label in TELEMETRY_PATTERNS:
                if pat.search(joined):
                    findings.append(Finding(
                        "high",
                        "Local-first policy risk",
                        f"`{path}`: {label}. The app must stay local-first; "
                        "telemetry is opt-in only.",
                        path,
                    ))
                    break
            for pat, label in DANGEROUS_CODE:
                if pat.search(joined):
                    findings.append(Finding(
                        "medium",
                        "Dangerous dynamic execution",
                        f"`{path}` adds {label}. Confirm the input is trusted "
                        "and sandboxed.",
                        path,
                    ))

        if len(fd.added) >= 400:
            findings.append(Finding(
                "medium",
                "Very large file change",
                f"`{path}` adds {len(fd.added)} lines. Consider splitting the PR.",
                path,
            ))

    if has_python_product_change and not has_test_change:
        findings.append(Finding(
            "medium",
            "Product Python changed without tests",
            "This diff touches `app/services`, `app/launch.py`, or `scripts/` "
            "but does not update `tests/`. Add or extend a regression test.",
        ))

    if has_ui_change:
        findings.append(Finding(
            "low",
            "UI changed — rebuild before merge",
            "Run `cd ui && npm run build` (CI already does this). Pinokio Update "
            "rebuilds for end users; keep `ui/dist` untracked.",
        ))

    if added_lines + removed_lines >= 1500:
        findings.append(Finding(
            "medium",
            "Large pull request",
            f"{added_lines} additions / {removed_lines} deletions. Reviewers "
            "will have an easier time with smaller, focused PRs.",
        ))

    if not files:
        findings.append(Finding(
            "low",
            "Empty diff",
            "No file changes were found. Check the base/head SHAs.",
        ))

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.title))
    return Review(
        files=files,
        findings=findings,
        areas=sorted(areas),
        added_lines=added_lines,
        removed_lines=removed_lines,
    )


def render_markdown(review: Review) -> str:
    risk = review.risk
    file_count = len(review.files)
    summary_bits = [
        f"{file_count} file(s)",
        f"+{review.added_lines}/-{review.removed_lines}",
    ]
    if review.areas:
        summary_bits.append(", ".join(review.areas))

    lines = [
        COMMENT_MARKER,
        "## PR Review — Loreframe Studio",
        "",
        f"**Risk:** {risk}  ",
        f"**Scope:** {'; '.join(summary_bits)}",
        "",
        "Automated review from `scripts/analyze_pr.py`. "
        "This is a heuristic pass (no LLM) so humans still own the merge decision.",
        "",
        "### Findings",
        "",
    ]

    if review.findings:
        for finding in review.findings:
            loc = f" (`{finding.path}`)" if finding.path else ""
            lines.append(f"- **{finding.severity}** — {finding.title}{loc}")
            lines.append(f"  {finding.detail}")
    else:
        lines.append("- No heuristic issues. Still run the CI checklist below.")

    lines.extend([
        "",
        "### Changed files",
        "",
    ])
    by_status: dict[str, list[str]] = defaultdict(list)
    for fd in review.files:
        label = fd.effective_path
        if fd.status == "renamed" and fd.new_path:
            label = f"{fd.path} → {fd.new_path}"
        by_status[fd.status].append(label)
    if review.files:
        for status in ("added", "modified", "renamed", "deleted"):
            paths = by_status.get(status)
            if not paths:
                continue
            lines.append(f"- **{status}:** " + ", ".join(f"`{p}`" for p in paths[:20]))
            if len(paths) > 20:
                lines.append(f"  … and {len(paths) - 20} more")
    else:
        lines.append("- _(none)_")

    lines.extend([
        "",
        "### CONTRIBUTING checklist",
        "",
        "- [ ] `python scripts/verify_clean_repo.py`",
        "- [ ] `python -m compileall -q app/services app/launch.py scripts`",
        "- [ ] `cd ui && npm run build` if the UI changed",
        "- [ ] No weights, CivitAI sidecars, or generated guides",
        "- [ ] Stays local-first (no required accounts / telemetry)",
        "",
        "_Posted by the repo PR review workflow. Re-runs on each push to the PR._",
        "",
    ])
    return "\n".join(lines)


def git_diff(base: str, head: str = "HEAD") -> str:
    result = subprocess.run(
        ["git", "-C", _REPO_ROOT, "diff", "--no-color", "--find-renames",
         f"{base}...{head}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout


def _read_diff(args: argparse.Namespace) -> str:
    if args.diff:
        if args.diff == "-":
            return sys.stdin.read()
        with open(args.diff, encoding="utf-8") as handle:
            return handle.read()
    base = args.base or "origin/main"
    return git_diff(base, args.head)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a Loreframe Studio PR diff.")
    parser.add_argument("--diff", help="Path to a unified diff, or - for stdin.")
    parser.add_argument("--base", help="Git base ref when --diff is omitted.")
    parser.add_argument("--head", default="HEAD", help="Git head ref (default HEAD).")
    parser.add_argument("--out", help="Write markdown review to this path.")
    parser.add_argument(
        "--fail-on",
        choices=("never", "high", "medium"),
        default="never",
        help="Exit 1 when findings at this severity or worse are present.",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        diff_text = _read_diff(args)
    except (OSError, RuntimeError) as exc:
        print(f"FAIL: could not read diff ({exc})", file=sys.stderr)
        return 2

    review = analyze_files(parse_unified_diff(diff_text))
    markdown = render_markdown(review)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)

    threshold = args.fail_on
    if threshold == "high" and review.risk == "high":
        return 1
    if threshold == "medium" and review.risk in {"high", "medium"}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
