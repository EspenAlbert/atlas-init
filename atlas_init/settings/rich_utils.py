import logging
from typing import Literal

from rich.console import Console
from rich.tree import Tree
import typer
from pydantic import BaseModel
from rich.logging import RichHandler


class _LogLevel(BaseModel):
    log_level: Literal["INFO", "WARNING", "ERROR", "CRITICAL"]


def remove_secrets(message: str, secrets: list[str]) -> str:
    for secret in secrets:
        message = message.replace(secret, "***")
    return message


class SecretsHider(logging.Filter):
    def __init__(self, secrets: list[str], name: str = "") -> None:
        self.secrets = secrets
        super().__init__(name)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = remove_secrets(record.msg, self.secrets)
        return True


dangerous_keys = ["key", "id", "secret"]
safe_keys: list[str] = ["/"]


def hide_secrets(handler: logging.Handler, secrets_dict: dict[str, str]) -> None:
    secrets_to_hide = set()
    for key, value in secrets_dict.items():
        if not isinstance(value, str):
            continue
        key_lower = key.lower()
        if key_lower in {"true", "false"} or value.lower() in {"true", "false"} or value.isdigit():
            continue
        if any(safe in key_lower for safe in safe_keys):
            continue
        if any(danger in key_lower for danger in dangerous_keys):
            secrets_to_hide.add(value)
    handler.addFilter(SecretsHider(list(secrets_to_hide), name="secrets-hider"))


def configure_logging(
    app: typer.Typer, log_level: str = "INFO", *, is_running_in_repo: bool = False
) -> logging.Handler:
    _LogLevel(log_level=log_level)  # type: ignore
    handler = RichHandler(rich_tracebacks=False, level=log_level)
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
    )
    if not is_running_in_repo or handler.level >= logging.WARNING:
        logging.warning("using basic tracebacks/errors")
        app.pretty_exceptions_enable = False
        app.pretty_exceptions_show_locals = False

    return handler


# https://github.com/Textualize/rich/blob/8c4d3d1d50047e3aaa4140d0ffc1e0c9f1df5af4/tests/test_live.py#L11
def create_capture_console(*, width: int = 60, height: int = 80, force_terminal: bool = True) -> Console:
    return Console(
        width=width,
        height=height,
        force_terminal=force_terminal,
        legacy_windows=False,
        color_system=None,  # use no color system to reduce complexity of output,
        _environ={},
    )


def tree_text(tree: Tree) -> str:
    console = create_capture_console()
    console.begin_capture()
    console.print(tree)
    return console.end_capture()
