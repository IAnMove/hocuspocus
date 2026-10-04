"""Build the community template index (and site files) from a folder of .hptemplate files.

Used by the community repository's CI: every package is validated with the same
code the app uses to import it, must live at ``templates/<author>/<slug>.hptemplate``
matching its id, and is published with its SHA-256 so the app can verify downloads.

    python scripts/community_index.py --templates templates --out _site \
        --base-url https://ianmove.github.io/hocuspocus-community

Needs only the standard library plus ``pydantic`` (imported by the app services).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from services.template_format import TemplateError  # noqa: E402
from services.template_library import TemplateLibrary  # noqa: E402

INDEX_KIND = "hocuspocus.community-index"


def _reader() -> TemplateLibrary:
    return TemplateLibrary(Path("."), workspace_dir=lambda name: name, reader=lambda workspace, filename: None)


def _entry(path: Path, templates: Path, out: Path, base_url: str, library: TemplateLibrary) -> dict:
    data = path.read_bytes()
    package = library.read_package(data)
    manifest = package["manifest"]
    expected = f"{path.parent.name}/{path.stem}"
    if path.suffix != ".hptemplate" or path.parent.parent != templates or manifest["id"] != expected:
        raise TemplateError(f"{path}: store it as templates/{manifest['id']}.hptemplate (id must match author/slug)")
    relative = f"templates/{manifest['id']}.hptemplate"
    (out / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, out / relative)
    preview = next((name for name in package["files"] if name.startswith("preview")), None)
    preview_url = None
    if preview:
        name = f"previews/{manifest['id'].replace('/', '--')}{Path(preview).suffix}"
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(package["files"][preview])
        preview_url = f"{base_url}/{name}"
    return {
        "id": manifest["id"], "editor": manifest["editor"], "title": manifest["title"], "description": manifest["description"],
        "tags": manifest["tags"], "author": manifest["author"], "license": manifest["license"],
        "templateVersion": manifest["templateVersion"], "requires": manifest["requires"],
        "slots": len(manifest["slots"]), "controls": len(manifest["controls"]), "media": len(manifest.get("media") or []),
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "package": f"{base_url}/{relative}", "preview": preview_url,
    }


def build(templates: Path, out: Path, base_url: str) -> tuple[dict, list[str]]:
    library = _reader()
    entries, errors = [], []
    base_url = base_url.rstrip("/")
    for path in sorted(templates.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.name == "README.md":
            continue
        try:
            entries.append(_entry(path, templates, out, base_url, library))
        except TemplateError as error:
            errors.append(f"{path}: {error}")
    seen: set[str] = set()
    for entry in entries:
        if entry["id"] in seen:
            errors.append(f"duplicate id {entry['id']}")
        seen.add(entry["id"])
    index = {"kind": INDEX_KIND, "version": 1, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "templates": sorted(entries, key=lambda item: item["title"].casefold())}
    return index, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--templates", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    index, errors = build(args.templates.resolve(), args.out.resolve(), args.base_url)
    for error in errors:
        print(f"::error::{error}")
    (args.out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(index['templates'])} templates, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
