from app.graph.tools.greeting import GREETING_TOOLS, say_hello


def test_say_hello_returns_a_greeting_with_the_name() -> None:
    result = say_hello.invoke({"name": "Synapse"})

    assert result == "Hello Synapse"


def test_greeting_tools_lists_exactly_say_hello() -> None:
    assert {t.name for t in GREETING_TOOLS} == {"say_hello"}
