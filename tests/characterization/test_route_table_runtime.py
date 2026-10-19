"""The served route table: every route the full server answers, in match order.

A move PR may change only the ``source`` of the routes it moves. Methods,
paths, endpoints, status codes, response models, OpenAPI ids and the order
stay the same. Refresh the fixture with ``scripts/architecture_contracts.py
--write`` and read its diff.
"""
from __future__ import annotations

import json
from collections import Counter

from tests.support.full_server import RUNTIME_ROUTE_FIXTURE, runtime_route_payload

REFRESH = "python scripts/architecture_contracts.py --write"


def _key(row: dict) -> tuple[str, str]:
    return row["method"], row["path"]


def _describe(expected: list[dict], served: list[dict]) -> str:
    before = {_key(row): row for row in expected}
    after = {_key(row): row for row in served}
    lines = [f"+ {' '.join(key)}" for key in after if key not in before]
    lines += [f"- {' '.join(key)}" for key in before if key not in after]
    for key in before.keys() & after.keys():
        changed = sorted(field for field in before[key] if before[key][field] != after[key].get(field))
        if changed:
            lines.append(f"~ {' '.join(key)}: {', '.join(changed)}")
    return "\n".join(sorted(lines)[:60])


def test_served_routes_match_the_runtime_fixture(full_server) -> None:
    served = runtime_route_payload(full_server.api)
    expected = json.loads(RUNTIME_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    assert served == expected, (
        f"The served route table differs from {RUNTIME_ROUTE_FIXTURE.name}. A move PR may change only "
        f"'source'. Refresh with `{REFRESH}` and review the diff.\n"
        + _describe(expected["routes"], served["routes"])
    )


def test_no_route_or_operation_id_is_served_twice(full_server) -> None:
    rows = runtime_route_payload(full_server.api)["routes"]
    routes = Counter(_key(row) for row in rows)
    operations = Counter(row["operation_id"] for row in rows if row["operation_id"])
    assert [key for key, count in routes.items() if count > 1] == []
    assert [key for key, count in operations.items() if count > 1] == []


def test_every_served_route_resolves_its_path(full_server) -> None:
    """No path keeps template text such as an f-string's braces around a name."""
    rows = runtime_route_payload(full_server.api)["routes"]
    assert all(row["path"].startswith("/") for row in rows)
    assert [row["path"] for row in rows if "{_" in row["path"] or "'" in row["path"]] == []
