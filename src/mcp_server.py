import os
from typing import Any
# pyrefly: ignore [missing-import]
from mcp.server.fastmcp import FastMCP
from src.claude_handler import ClaudeHandler
from src.models import Employee

mcp = FastMCP("BetterUpSyncEngine")


@mcp.tool()
def resolve_identity_conflict(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    context: str = "",
) -> dict[str, Any]:
    """Resolves ambiguous identity conflicts between two employee records.

    Constructs canonical Employee models from input dictionaries and delegates
    to ClaudeHandler for confidence-gated conflict resolution.
    """
    try:
        emp_a = Employee.model_validate(record_a)
        emp_b = Employee.model_validate(record_b)
    except Exception as e:
        return {
            "decision": "needs_human_review",
            "confidence": 0.0,
            "reasoning": f"Invalid employee record format: {e}",
        }

    handler = ClaudeHandler()
    resolution = handler.resolve_conflict(emp_a, emp_b, context)
    return resolution.model_dump()


def run() -> None:
    """Run the MCP server using standard I/O transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
