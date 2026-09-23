"""Greeting tool bound to the `greeting` node."""

from langchain_core.tools import tool


@tool
def say_hello(name: str) -> str:
    """Return a friendly greeting for `name`."""
    return f"Hello {name}"


GREETING_TOOLS = [say_hello]
