"""Check or regenerate the TypeScript contract for Series Assembly.

The OpenAPI fixture is deliberately limited to the Series Assembly surface;
this command must not import the GPU-heavy application launcher.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/series-lab/series-assembly.openapi.json"
TS_TARGET = ROOT / "ui/src/features/series/assemblyContract.ts"


def _schema_type(schema: dict, *, property_name: str = "") -> str:
    reference = schema.get("$ref")
    if reference:
        return reference.rsplit("/", 1)[-1]
    enum = schema.get("enum")
    if enum and property_name == "status":
        return "SeriesAssemblyStatus"
    variants = schema.get("anyOf")
    if variants:
        return " | ".join(_schema_type(item, property_name=property_name) for item in variants)
    kind = schema.get("type")
    if kind == "array":
        return f"{_schema_type(schema.get('items') or {})}[]"
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


def render_types(spec: dict) -> str:
    schemas = spec["components"]["schemas"]
    status_values = schemas["SeriesAssemblyJobResponse"]["properties"]["status"]["enum"]
    lines = [
        "/**",
        " * Generated from docs/series-lab/series-assembly.openapi.json.",
        " * Do not edit manually; run scripts/check_series_assembly_contract.py --write.",
        " */",
        "",
        "export type SeriesAssemblyStatus = " + " | ".join(repr(value) for value in status_values),
        "",
    ]
    for name in (
        "SeriesAssemblyStartRequest", "SeriesAssemblyActionRequest",
        "SeriesAssemblyJobResponse", "SeriesAssemblyRecoveryResponse",
        "SeriesAssemblyDiscardResponse",
    ):
        schema = schemas[name]
        required = set(schema.get("required", []))
        lines.append(f"export interface {name} {{")
        for property_name, property_schema in schema["properties"].items():
            optional = "" if property_name in required else "?"
            lines.append(
                f"  {property_name}{optional}: "
                f"{_schema_type(property_schema, property_name=property_name)}"
            )
        lines.extend(["}", ""])
    lines.append("export type SeriesAssemblyJob = SeriesAssemblyJobResponse")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check without writing (default)")
    parser.add_argument("--write", action="store_true", help="write the generated TypeScript file")
    args = parser.parse_args()
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    generated = render_types(spec)
    if args.write:
        TS_TARGET.write_text(generated, encoding="utf-8")
        print(f"wrote {TS_TARGET.relative_to(ROOT)}")
        return 0
    current = TS_TARGET.read_text(encoding="utf-8") if TS_TARGET.exists() else ""
    if current != generated:
        print(f"Series Assembly TypeScript contract is stale: {TS_TARGET}", file=sys.stderr)
        return 1
    print("Series Assembly TypeScript contract is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
