"""The shared tool-execution node and its fixed allowlist.

One tool-execution node for the whole graph — see `.agents/skills/graph/SKILL.md`.
`ToolNode` refuses to run anything not in the list it was built with: the
model's own output can request a tool by name, but it never adds to what is
actually dispatchable. `ALLOWED_TOOLS` is that list, declared in code.
"""

from langgraph.prebuilt import ToolNode

from app.graph.tools.arithmetic import ARITHMETIC_TOOLS

ALLOWED_TOOLS = [*ARITHMETIC_TOOLS]


def get_tool_node() -> ToolNode:
    """Build the shared tool-execution node."""
    return ToolNode(tools=ALLOWED_TOOLS)
