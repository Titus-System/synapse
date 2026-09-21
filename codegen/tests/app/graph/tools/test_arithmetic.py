from app.graph.tools.arithmetic import ARITHMETIC_TOOLS, add, multiply, subtract


def test_add_returns_the_sum() -> None:
    result = add.invoke({"a": 40, "b": 12})

    assert result == 52


def test_subtract_returns_a_minus_b() -> None:
    result = subtract.invoke({"a": 10, "b": 3})

    assert result == 7


def test_multiply_returns_the_product() -> None:
    result = multiply.invoke({"a": 6, "b": 7})

    assert result == 42


def test_arithmetic_tools_lists_exactly_add_subtract_multiply() -> None:
    assert {t.name for t in ARITHMETIC_TOOLS} == {"add", "subtract", "multiply"}
