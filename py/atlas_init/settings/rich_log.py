import logging
from typing import Literal
from pydantic import BaseModel
from rich.logging import RichHandler

class _LogLevel(BaseModel):
    log_level: Literal["INFO", "WARNING", "ERROR", "CRITICAL"]

def configure_logging(log_level: str = "INFO"):
    _LogLevel(log_level=log_level) # type: ignore
    logging.basicConfig(
        level=logging.getLevelName(log_level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
