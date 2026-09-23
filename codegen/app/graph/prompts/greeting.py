"""Prompt sent by the `greeting` node.

Fixed text: nothing from the job or the user is interpolated, so no untrusted input can reach
the tool call it asks for (AGENTS.md Security).
"""

GREETING_PROMPT = (
    'Greet the Synapse team: call the `say_hello` tool with the name "Synapse", '
    "then reply with the greeting it returns."
)
