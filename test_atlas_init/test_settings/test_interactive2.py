import pytest

from atlas_init.settings.interactive2 import (
    KeyInput,
    confirm,
    question_patcher,
    select_list,
    select_list_multiple,
    text,
)


def test_confirm():
    with question_patcher(["y", "n", "", ""]):
        assert confirm("Can you confirm? (should answer yes)")
        assert not confirm("Can you confirm? (should answer no)")
        assert confirm("Can you confirm? (use default yes)", default=True)
        assert not confirm("Can you confirm? (use default no)", default=False)


def test_text():
    with question_patcher(["Jane Doe", ""]):
        assert text("Enter your name:") == "Jane Doe"
        assert text("Enter your name:", default="John Doe") == "John Doe"


@pytest.mark.parametrize(
    "inputs, options, expected",
    [
        ([""], ["Option 1", "Option 2"], []),
        ([" "], ["Option 1", "Option 2"], ["Option 1"]),
        ([f"{KeyInput.DOWN} "], ["Option 1", "Option 2"], ["Option 2"]),
        ([f" {KeyInput.DOWN} "], ["Option 1", "Option 2"], ["Option 1", "Option 2"]),
    ],
    ids=[
        "empty selection",
        "single selection",
        "second option selection",
        "multiple selection",
    ],
)
def test_select_list_multiple(inputs, options, expected):
    with question_patcher(inputs):
        assert select_list_multiple("Select options:", options) == expected


@pytest.mark.parametrize(
    "inputs, options, default, expected",
    [
        ([""], ["Option 1", "Option 2", "Option 3"], None, "Option 1"),
        ([f"{KeyInput.DOWN}"], ["Option 1", "Option 2", "Option 3"], None, "Option 2"),
        ([""], ["Option 1", "Option 2", "Option 3"], "Option 2", "Option 2"),
        (
            [f"{KeyInput.DOWN}"],
            ["Option 1", "Option 2", "Option 3"],
            "Option 1",
            "Option 2",
        ),
        (
            [f"{KeyInput.DOWN}"],
            ["Option 1", "Option 2", "Option 3"],
            "Option 2",
            "Option 3",
        ),
    ],
    ids=[
        "first option no default",
        "second option no default",
        "option 2 is default and selected",
        "option 1 is default, select option 2",
        "option 2 is default, select option 3",
    ],
)
def test_select_list(inputs, options, default, expected):
    with question_patcher(inputs):
        assert select_list("Select an option:", options, default=default) == expected
