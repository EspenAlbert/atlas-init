import logging
from typing import Literal

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
        if key_lower in {"true", "false"}:
            continue
        if any(safe in key_lower for safe in safe_keys):
            continue
        if any(danger in key_lower for danger in dangerous_keys):
            secrets_to_hide.add(value)
    handler.addFilter(SecretsHider(list(secrets_to_hide), name="secrets-hider"))


def configure_logging(log_level: str = "INFO") -> logging.Handler:
    _LogLevel(log_level=log_level)  # type: ignore
    handler = RichHandler(rich_tracebacks=True)
    logging.basicConfig(
        level=logging.getLevelName(log_level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
    )
    return handler
