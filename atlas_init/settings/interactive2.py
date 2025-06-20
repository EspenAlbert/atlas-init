"""Inspired by: https://github.com/tmbo/questionary/blob/master/tests/utils.py"""

from dataclasses import dataclass
from typing import Callable, TypeVar

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from questionary import Question, checkbox
from questionary import confirm as _confirm
from questionary import select as _select
from questionary import text as _text

T = TypeVar("T")
TypedAsk = Callable[[Question, type[T]], T]

_question_asker: TypedAsk = lambda q, _: q.ask()  # noqa: E731


def confirm(prompt_text: str, *, default: bool | None = None) -> bool:
    if default is None:
        return _question_asker(_confirm(prompt_text), bool)
    return _question_asker(_confirm(prompt_text, default=default), bool)


def select_list_multiple(
    prompt_text: str,
    choices: list[str],
    default: list[str] | None = None,
) -> list[str]:
    assert choices, "choices must not be empty"
    default = default or []
    return _question_asker(checkbox(prompt_text, choices=choices), list[str]) or default


def text(
    prompt_text: str,
    default: str = "",
) -> str:
    return _question_asker(_text(prompt_text, default=default), str)


T = TypeVar("T")


def select_dict(
    prompt_text: str,
    choices: dict[str, T],
    default: str | None = None,
) -> T:
    assert choices, "choices must not be empty"
    selection = _question_asker(_select(prompt_text, default=default, choices=list(choices)), str)
    return choices[selection]


StrT = TypeVar("StrT", bound=str)


def select_list(
    prompt_text: str,
    choices: list[StrT],
    default: StrT | None = None,
) -> StrT:
    assert choices, "choices must not be empty"
    return _question_asker(_select(prompt_text, default=default, choices=choices), str)


class KeyInput:
    DOWN = "\x1b[B"
    UP = "\x1b[A"
    LEFT = "\x1b[D"
    RIGHT = "\x1b[C"
    ENTER = "\r"
    ESCAPE = "\x1b"
    CONTROLC = "\x03"
    CONTROLN = "\x0e"
    CONTROLP = "\x10"
    BACK = "\x7f"
    SPACE = " "
    TAB = "\x09"
    ONE = "1"
    TWO = "2"
    THREE = "3"


@dataclass
class question_patcher:
    responses: list[str]
    next_response: int = 0

    def __enter__(self):
        global _question_asker
        self._old_patcher = _question_asker
        _question_asker = self.ask_question
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _question_patcher
        _question_patcher = self._old_patcher

    def ask_question(self, q: Question, response_type: type[T]) -> T:
        q.application.output = DummyOutput()

        def run(inp) -> T:
            try:
                input_response = self.responses[self.next_response]
            except IndexError:
                raise ValueError(
                    f"Not enough responses provided. Expected {len(self.responses)}, got {self.next_response + 1} questions."
                )
            self.next_response += 1
            inp.send_text(input_response + KeyInput.ENTER + "\r")
            q.application.output = DummyOutput()
            q.application.input = inp
            return q.ask()

        with create_pipe_input() as inp:
            return run(inp)


if __name__ == "__main__":
    print(select_list("Select an option:", ["Option 1", "Option 2", "Option 3"]))  # noqa: T201
    print(  # noqa: T201
        select_dict(
            "Select an option:",
            {"Option 1": "1", "Option 2": "2", "Option 3": "3"},
            default="Option 3",
        )
    )
    print(confirm("Can you confirm?", default=True))  # noqa: T201
    print(confirm("Can you confirm?", default=False))  # noqa: T201
    print(  # noqa: T201
        select_list_multiple("Select options:", ["Option 1", "Option 2", "Option 3"], ["Option 1"])
    )
    print(text("Enter your name:", default="John Doe"))  # noqa: T201
