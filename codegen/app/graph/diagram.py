"""Renders the graph as a Mermaid diagram in `docs/graph.md`.

Run through `make graph`. `tests/app/graph/test_diagram.py` fails when the committed file no
longer matches the graph. Mermaid text is used rather than PNG: it diffs in review, and
`draw_mermaid_png` sends the graph's structure to an external service.
"""

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.graph.core.engine import build_graph

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "graph.md"

_HEADER = """\
# Graph

Generated from `app/graph/core/engine.py`; do not edit by hand. Regenerate with `make graph`.

"""


def render_doc() -> str:
    """Full content of `docs/graph.md` for the graph as currently built."""
    # Drawing only needs the topology, so no database connection is opened for it.
    mermaid = build_graph(InMemorySaver()).get_graph().draw_mermaid()
    return f"{_HEADER}```mermaid\n{mermaid.rstrip()}\n```\n"


def main() -> None:
    DOC_PATH.write_text(render_doc(), encoding="utf-8")


if __name__ == "__main__":
    main()
