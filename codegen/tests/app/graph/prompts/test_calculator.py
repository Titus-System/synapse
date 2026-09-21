import re

from langchain_core.messages import SystemMessage

from app.graph.prompts.calculator import SYSTEM_PROMPT
from app.graph.tools.arithmetic import ARITHMETIC_TOOLS


def test_system_prompt_is_a_system_message() -> None:
    assert isinstance(SYSTEM_PROMPT, SystemMessage)


def test_system_prompt_does_not_name_any_tool() -> None:
    """Tool schemas arrive through `bind_tools`; naming them here would let the two drift apart."""
    content = str(SYSTEM_PROMPT.content)

    named = [t.name for t in ARITHMETIC_TOOLS if re.search(rf"\b{t.name}\b", content)]

    assert named == []
