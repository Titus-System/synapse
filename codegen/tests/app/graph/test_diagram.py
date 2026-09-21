from app.graph.diagram import DOC_PATH, render_doc


def test_committed_graph_diagram_matches_the_graph() -> None:
    assert (
        DOC_PATH.read_text(encoding="utf-8") == render_doc()
    ), "docs/graph.md is out of date: run `make graph` and commit the result"
