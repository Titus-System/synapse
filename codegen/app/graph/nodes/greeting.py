"""`greeting` node: the first node after `START`, bound to `GREETING_TOOLS`.

When the model requests `say_hello`, the shared tool-execution node
(`app/graph/core/tool_dispatch.py`) runs it and the result loops back here - see
`.agents/skills/graph/SKILL.md`.
"""

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logger import get_logger, no_ctx
from app.graph.core.llm.registry import get_model
from app.graph.core.state import AgentState
from app.graph.prompts.greeting import GREETING_PROMPT
from app.graph.tools.greeting import GREETING_TOOLS

logger = get_logger("app.graph.nodes.greeting")


async def greeting(state: AgentState, config: RunnableConfig) -> AgentState:
    """Ask the `greeting` model to greet through `say_hello`.

    The prompt is only sent once: on the first call, `messages` is still empty, so a
    `HumanMessage` with it is added to the history; a call after a tool loop reuses that
    history instead of adding the prompt again.
    """
    existing_messages = list(state.get("messages") or [])
    new_messages: list[BaseMessage] = []

    if not existing_messages:
        new_messages.append(HumanMessage(content=GREETING_PROMPT))

    token = no_ctx.set("greeting")
    try:
        model = get_model("greeting").bind_tools(GREETING_TOOLS)
        response = await model.ainvoke([*existing_messages, *new_messages])
        new_messages.append(response)

        if getattr(response, "tool_calls", None):
            logger.info(
                "greeting requested a tool call",
                extra={"tools": [chamada["name"] for chamada in response.tool_calls]},
            )
        else:
            logger.info("greeting model call finished")
        return {"messages": new_messages}
    finally:
        no_ctx.reset(token)
