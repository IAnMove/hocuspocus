"""Turn a template-submission issue into a validated file ready for a pull request.

Reads the issue body (GitHub issue form), downloads the attached .zip from
github.com/user-attachments, validates it with HocusPocus's own importer and
writes templates/<author>/<slug>.hptemplate. Prints key=value lines for the workflow.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path("hocuspocus/app").resolve()))
from services.template_format import TemplateError  # noqa: E402
from services.template_library import MAX_ZIP_BYTES, TemplateLibrary  # noqa: E402

ATTACHMENT = re.compile(r"https://github\.com/(?:user-attachments/files|[^/\s]+/[^/\s]+/files)/[^\s)]+\.zip")


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    match = ATTACHMENT.search(body)
    if not match:
        print("error=No .zip attachment found. Rename the .hptemplate to .zip and attach it.")
        return 0
    request = urllib.request.Request(match.group(0), headers={"User-Agent": "hocuspocus-community-bot"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed GitHub host
        data = response.read(MAX_ZIP_BYTES + 1)
    if len(data) > MAX_ZIP_BYTES:
        print("error=The file is larger than 64 MB.")
        return 0
    library = TemplateLibrary(Path("."), workspace_dir=lambda name: name, reader=lambda workspace, filename: None)
    try:
        manifest = library.read_package(data)["manifest"]
    except TemplateError as error:
        print(f"error=Invalid template: {error}")
        return 0
    target = Path("templates") / f"{manifest['id']}.hptemplate"
    exists = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"id={manifest['id']}")
    print(f"path={target}")
    print(f"update={'true' if exists else 'false'}")
    print(f"title={manifest['title'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
