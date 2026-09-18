from langchain_core.tools import tool


@tool
def worker() -> None:
    """This is a worker function that performs a task."""
    return None
