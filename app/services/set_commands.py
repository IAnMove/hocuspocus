"""Read-only mold discovery shared by MCP and REST."""
from services.set_molds import catalog

OPERATION = "scene3d.sets.catalog"


def command_catalog():
    return [{"name": OPERATION, "version": 1, "domain": "scenes", "mutation": False, "destructive": False,
             "description": "List the interior and exterior molds (kind, title) with sizes, surfaces, character marks, cameras and prop anchors.",
             "inputSchema": {"type": "object", "required": ["version", "input"], "additionalProperties": False,
                             "properties": {"version": {"const": 1}, "input": {"type": "object", "additionalProperties": False,
                                 "properties": {"workspace": {"type": "string"}}}}}}]


def command_handlers():
    async def run(arguments):
        return {"version": 1, "operation": OPERATION, "status": "completed", "result": {"molds": catalog()}}
    return {OPERATION: run}


