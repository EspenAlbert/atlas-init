from logging import Logger
from pathlib import Path
import subprocess
import sys


def run_command_is_ok(
    cmd: list[str], env: dict, cwd: Path | str, logger: Logger
) -> bool:
    command_str = " ".join(cmd)
    logger.info(f"running: {command_str}")
    exit_code = subprocess.call(
        cmd,
        stdin=sys.stdin,
        stderr=sys.stderr,
        stdout=sys.stdout,
        cwd=cwd,
        env=env,
    )
    is_ok = exit_code == 0
    if is_ok:
        logger.info(f"success 🥳 '{command_str}'")
        logger.info("")
    else:
        logger.error(f"error 💥, exit code={exit_code}, '{command_str}'")
    return is_ok
