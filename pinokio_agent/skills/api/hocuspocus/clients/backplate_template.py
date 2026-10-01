"""Pack and import the PS1 scene through the public template library API; no GPU."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

TEMPLATE_ID = "hocuspocus/ps1-backplates"
DEFINITION = Path(__file__).with_name("ps1_backplates_template.json")
PREVIEW_SIGNATURES = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".webp": b"RIFF"}


def template_definition() -> dict:
    """Read fresh data so callers can author variations without mutating the source."""
    return json.loads(DEFINITION.read_text(encoding="utf-8"))


def build_package(preview: bytes | None = None, *, preview_suffix: str = ".png") -> bytes:
    """A portable template with empty asset slots and an optional existing preview."""
    definition = template_definition()
    manifest = definition["manifest"]
    members = {"document.json": definition["document"]}
    if preview is not None:
        signature = PREVIEW_SIGNATURES.get(preview_suffix)
        if not signature or not preview.startswith(signature) or len(preview) > 2 * 1024 * 1024:
            raise ValueError("Use an existing PNG, JPEG or WebP preview up to 2 MB")
        if preview_suffix == ".webp" and preview[8:12] != b"WEBP":
            raise ValueError("Use an existing WebP image, not another RIFF file")
        manifest["preview"] = "preview" + preview_suffix
    members["template.json"] = manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(members.items()):
            _write_member(archive, name, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
        if preview is not None:
            _write_member(archive, manifest["preview"], preview)
    return buffer.getvalue()


def _write_member(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    member = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
    member.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(member, data)


def _post_package(base_url: str, path: str, package: bytes) -> dict:
    request = Request(base_url.rstrip("/") + path, package, {"Content-Type": "application/zip"}, method="POST")
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def import_template(base_url: str, package: bytes) -> dict:
    """Preflight first; never overwrite someone's existing template."""
    report = _post_package(base_url, "/api/v1/templates/preflight", package)
    if not report.get("canImport") or report.get("template", {}).get("id") != TEMPLATE_ID:
        raise ValueError("The package did not pass the PS1 template preflight")
    if report.get("exists"):
        raise ValueError("The PS1 template already exists; use the library to review any replacement")
    return _post_package(base_url, "/api/v1/templates/import", package)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New .hptemplate file")
    parser.add_argument("--preview", type=Path, help="Existing approved frame; no image is generated")
    parser.add_argument("--base-url", help="Discovered HocusPocus API URL; optionally import into its library")
    args = parser.parse_args()
    suffix = args.preview.suffix.lower().replace(".jpeg", ".jpg") if args.preview else ".png"
    package = build_package(args.preview.read_bytes() if args.preview else None, preview_suffix=suffix)
    with args.output.open("xb") as handle:
        handle.write(package)
    result = {"file": str(args.output), "bytes": len(package), "id": TEMPLATE_ID}
    if args.base_url:
        result["imported"] = import_template(args.base_url, package)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
