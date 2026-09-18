"""The calculator node: answers using the arithmetic tools when needed."""

from app.graph.core.llm.registry import get_model
from app.graph.core.state import AgentState
from app.graph.prompts.calculator import SYSTEM_PROMPT
from app.graph.tools.arithmetic import ARITHMETIC_TOOLS


def calculator_node(state: AgentState) -> AgentState:
    """Invoke the model, bound to the arithmetic tools, on the message history so far."""
    model = get_model("calculator").bind_tools(ARITHMETIC_TOOLS)
    response = model.invoke([SYSTEM_PROMPT, *state["messages"]])
    return {"messages": [response]}
