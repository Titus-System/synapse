"""Prompt(s) for the calculator node."""

from langchain_core.messages import SystemMessage

SYSTEM_PROMPT = SystemMessage(
    content="You are my AI assistant, please answer my query to the best of your ability."
)
