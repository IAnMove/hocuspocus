#!/usr/bin/env python3
"""Write a compact architecture map so an agent does not have to explore.

The committed file is ``docs/ARCHITECTURE_MAP.md``. ``--check`` compares it
with a fresh render and does not write. Output is sorted and has no timestamps
and no absolute paths. This script is not a CI gate.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_LINES = 400
DOC_LIMIT = 90
OUTPUT = ROOT / "docs" / "ARCHITECTURE_MAP.md"
ALWAYS_TABLE = {
    "Routers",
    "UI slices",
    "services/kernel",
    "services/generation_worker",
    "services/generation",
    "services/engine",
}
NAMED_PACKAGES = ("kernel", "generation_worker", "generation", "engine")
TOKEN = re.compile(r"(?<![\w.])((?:app\.)?(?:routers|services)(?:[./][\w]+)+)")
FROM_IMPORT = re.compile(r"^from\s+([\w.]+)\s+import\s+(\([^)]*\)|[^\n#]+)", re.M)
ABSOLUTE = re.compile(r"(?:/mnt/|/home/|[A-Za-z]:\\)\S+")

INTRO = """\
# Architecture map

Agent map of this tree. Regenerate with `python scripts/dev/architecture_map.py`. Do not edit by hand. The Story Lab audio graph is a different file: `docs/development/ARCHITECTURE_MAP.md`.

## How the system is composed

From `docs/development/ARCHITECTURE_FOUNDATION.md`, `docs/development/CODE_HEALTH.md`, `scripts/size_ceilings.json` and `app/_launch_runtime.py`.

- `app/_launch_runtime.py` is the full server and `app/core_runtime.py` is the core server. They compose imports, `api.include_router(...)` and one keyword-only `bind(...)` per moved module. Ceilings in `scripts/size_ceilings.json` (3028 and 580) only go down.
- HTTP routes live in `app/routers/*`. Static order is `tests/fixtures/route_table.json`. Served order is `tests/fixtures/route_table_runtime.json`. Refresh with `scripts/architecture_contracts.py --write`.
- Logic lives in `app/services/*`. The shared kernel is `app/services/kernel/`. A service does not import a router. WanGP stays behind `app/services/generation/` (`bind_wgp`, `get_wgp()`).
- Names a module needs from launch arrive through that one `bind(**names)`, called once from launch and stored as plain module globals. No proxies and no `sys.modules` lookups.
- `ui/src/stores/useStore.ts` (ceiling 116) only composes slices in `ui/src/stores/` and `ui/src/features/*/store`. UI tests are node:test via tsx.
- `app/wgp.py` and `app/models/**` are upstream WanGP.

Mount is `launch`, `core`, `both`, or `ui` when `useStore.ts` imports the slice. Tests lists up to three files that mention the module path. Sections that do not fit stay indexed as `path (lines mount)`.
"""


@dataclass(frozen=True)
class Row:
    path: str
    doc: str
    lines: int
    mount: str
    tests: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _cell(text: str) -> str:
    flat = " ".join(text.split())
    flat = flat.replace("|", "/")
    flat = ABSOLUTE.sub("(path)", flat)
    flat = flat.replace("`", "'")
    if not flat:
        return "—"
    if len(flat) <= DOC_LIMIT:
        return flat
    return flat[: DOC_LIMIT - 1] + "…"


def _py_doc(text: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(text)) or ""
    except SyntaxError:
        return "—"
    if not doc.strip():
        return "—"
    return _cell(doc.strip().splitlines()[0])


def _ts_doc(text: str) -> str:
    block = re.match(r"\s*/\*\*(.*?)\*/", text, re.S)
    if block:
        raw = block.group(1).strip().splitlines()[0]
        return _cell(re.sub(r"^\*\s?", "", raw.strip()))
    line = re.match(r"\s*//\s?(.+)", text)
    if line:
        return _cell(line.group(1))
    return "—"


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _scan_imports(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    refs: set[str] = set()
    for match in TOKEN.findall(text):
        refs.add(_token_key(match))
    pairs: set[tuple[str, str]] = set()
    for match in FROM_IMPORT.finditer(text):
        module = match.group(1)
        if module.startswith("app."):
            module = module[4:]
        body = match.group(2).replace("(", " ").replace(")", " ")
        for part in body.split(","):
            name = part.strip().split(" as ")[0].strip()
            if name.isidentifier():
                pairs.add((module, name))
    return refs, pairs


def _token_key(match: str) -> str:
    key = match.replace("/", ".")
    if key.startswith("app."):
        key = key[4:]
    if key.endswith(".py"):
        key = key[:-3]
    return key


def _hit(dotted: str, refs: set[str], pairs: set[tuple[str, str]]) -> bool:
    if dotted in refs or any(ref.startswith(dotted + ".") for ref in refs):
        return True
    parent, _, stem = dotted.rpartition(".")
    if parent and (parent, stem) in pairs:
        return True
    return any(module == dotted or module.startswith(dotted + ".") for module, _name in pairs)


def _mount_py(dotted: str, launch: tuple, core: tuple) -> str:
    on_launch = _hit(dotted, launch[0], launch[1])
    on_core = _hit(dotted, core[0], core[1])
    if on_launch and on_core:
        return "both"
    if on_launch:
        return "launch"
    if on_core:
        return "core"
    return "—"


def _dotted(rel: str) -> str:
    """``app/services/kernel/context.py`` -> ``services.kernel.context``."""
    module = rel[len("app/"):-3] if rel.endswith(".py") else rel
    if module.endswith("/__init__"):
        module = module[: -len("/__init__")]
    return module.replace("/", ".")


def _corpus(root: Path) -> list[tuple[str, str]]:
    folder = root / "tests"
    files = []
    for path in folder.rglob("*.py"):
        if "__pycache__" in path.parts or not path.name.startswith("test_"):
            continue
        files.append(path)
    files.sort(key=lambda item: item.relative_to(root).as_posix())
    return [(path.relative_to(root).as_posix(), _read(path)) for path in files]


def _test_index(corpus: list[tuple[str, str]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for rel, text in corpus:
        seen: set[str] = set()
        for match in TOKEN.findall(text):
            key = _token_key(match)
            if key in seen:
                continue
            seen.add(key)
            index.setdefault(key, []).append(rel)
    return index


def _tests_cell(keys: list[str], index: dict[str, list[str]]) -> str:
    hits: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for rel in index.get(key, []):
            if rel in seen:
                continue
            seen.add(rel)
            hits.append(rel)
            if len(hits) == 3:
                return ", ".join(hits)
    return ", ".join(hits) if hits else "—"


def _py_rows(root: Path, folder: Path, launch: tuple, core: tuple, index: dict[str, list[str]]) -> list[Row]:
    rows: list[Row] = []
    paths = [path for path in folder.rglob("*.py") if "__pycache__" not in path.parts]
    paths.sort(key=lambda item: item.relative_to(root).as_posix())
    for path in paths:
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        dotted = _dotted(rel)
        rows.append(Row(
            rel,
            _py_doc(text),
            _line_count(text),
            _mount_py(dotted, launch, core),
            _tests_cell([dotted], index),
        ))
    return rows


def _is_slice(path: Path) -> bool:
    if path.suffix not in {".ts", ".tsx"}:
        return False
    if path.name in {"useStore.ts", "storeApi.ts"}:
        return False
    stem = path.stem
    return stem == "store" or stem.endswith("Slice") or stem.endswith("Store")


def _ui_mounted(rel: str, store_text: str) -> bool:
    marker = rel[len("ui/src/"):].rsplit(".", 1)[0] if rel.startswith("ui/src/") else rel
    if marker in store_text:
        return True
    stem = Path(rel).stem
    return stem not in {"store", "index"} and stem in store_text


def _ui_tests(rel: str, corpus: list[tuple[str, str]]) -> str:
    marker = rel[len("ui/"):] if rel.startswith("ui/") else rel
    stem = Path(rel).stem
    hits: list[str] = []
    for path, text in corpus:
        mentioned = marker in text or (stem not in {"store", "index"} and stem in text)
        if not mentioned:
            continue
        hits.append(path)
        if len(hits) == 3:
            break
    return ", ".join(hits) if hits else "—"


def _ui_rows(root: Path, store_text: str, corpus: list[tuple[str, str]]) -> list[Row]:
    found: list[Path] = []
    for folder in (root / "ui" / "src" / "stores", root / "ui" / "src" / "features"):
        if not folder.is_dir():
            continue
        found.extend(path for path in folder.rglob("*") if path.is_file() and _is_slice(path))
    found.sort(key=lambda item: item.relative_to(root).as_posix())
    rows: list[Row] = []
    for path in found:
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        mount = "ui" if _ui_mounted(rel, store_text) else "—"
        rows.append(Row(rel, _ts_doc(text), _line_count(text), mount, _ui_tests(rel, corpus)))
    return rows


def _sections(root: Path) -> list[tuple[str, list[Row]]]:
    launch = _scan_imports(_read(root / "app" / "_launch_runtime.py"))
    core = _scan_imports(_read(root / "app" / "core_runtime.py"))
    store_text = _read(root / "ui" / "src" / "stores" / "useStore.ts")
    corpus = _corpus(root)
    index = _test_index(corpus)
    sections: list[tuple[str, list[Row]]] = [
        ("Routers", _py_rows(root, root / "app" / "routers", launch, core, index)),
    ]
    services = _py_rows(root, root / "app" / "services", launch, core, index)
    grouped: dict[str, list[Row]] = {}
    for row in services:
        parts = row.path.split("/")
        title = "services" if len(parts) == 3 else f"services/{parts[2]}"
        grouped.setdefault(title, []).append(row)
    for name in NAMED_PACKAGES:
        title = f"services/{name}"
        sections.append((title, grouped.pop(title, [])))
    for title in sorted(key for key in grouped if key != "services"):
        sections.append((title, grouped[title]))
    sections.append(("UI slices", _ui_rows(root, store_text, corpus)))
    sections.append(("services", grouped.get("services", [])))
    return sections


def _table(title: str, rows: list[Row]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Module | Doc | Lines | Mount | Tests |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| `{row.path}` | {row.doc} | {row.lines} | {row.mount} | {row.tests} |")
    lines.append("")
    return lines


def _index(title: str, rows: list[Row], width: int) -> list[str]:
    lines = [f"## {title}", ""]
    current = ""
    for row in rows:
        piece = f"`{row.path}` ({row.lines} {row.mount})"
        if not current:
            current = piece
            continue
        if len(current) + 2 + len(piece) <= width:
            current = f"{current}, {piece}"
            continue
        lines.append(current)
        current = piece
    if current:
        lines.append(current)
    lines.append("")
    return lines


def _row_count(sections: list[tuple[str, list[Row]]], title: str) -> int:
    for name, rows in sections:
        if name == title:
            return len(rows)
    return 0


def _render_lines(sections: list[tuple[str, list[Row]]], modes: dict[str, str], width: int) -> list[str]:
    lines = INTRO.splitlines()
    lines.append("")
    for title, rows in sections:
        if not rows:
            continue
        if modes[title] == "table":
            lines.extend(_table(title, rows))
        else:
            lines.extend(_index(title, rows, width))
    return lines


def _fit(sections: list[tuple[str, list[Row]]]) -> list[str]:
    modes = {title: "table" for title, _rows in sections}
    width = 120
    while True:
        lines = _render_lines(sections, modes, width)
        if len(lines) <= MAX_LINES:
            return lines
        convertible = [
            title for title, rows in sections
            if rows and modes[title] == "table" and title not in ALWAYS_TABLE
        ]
        if convertible:
            biggest = max(convertible, key=lambda title: _row_count(sections, title))
            modes[biggest] = "index"
            continue
        # Index rows wrap at `width`. 240 left this tree at 414 lines, over MAX_LINES.
        if width < 400:
            width += 40
            continue
        return lines


def render(root: Path | None = None) -> str:
    """Deterministic markdown. The same tree always produces the same text."""
    base = root or ROOT
    lines = _fit(_sections(base))
    return "\n".join(lines).rstrip() + "\n"


def composition_line_count() -> int:
    """Lines of the 'how it is composed' section, including its heading."""
    text = INTRO.split("## How the system is composed", 1)[1]
    body = "## How the system is composed" + text
    return len(body.strip("\n").splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed map is stale")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    expected = render(args.root)
    output = args.output
    if args.check:
        actual = output.read_text(encoding="utf-8") if output.is_file() else ""
        if actual != expected:
            print(f"{output} is stale. Run python scripts/dev/architecture_map.py")
            return 1
        print(f"{output} is current")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"wrote {output} ({len(expected.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
