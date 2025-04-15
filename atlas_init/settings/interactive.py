import logging

from rich import prompt

logger = logging.getLogger(__name__)


def confirm(prompt_text: str, *, is_interactive: bool, default: bool) -> bool:
    if not is_interactive:
        logger.warning(f"non-interactive prompt: {prompt_text}, using default={default}")
        return default
    return prompt.Confirm(prompt_text)()
