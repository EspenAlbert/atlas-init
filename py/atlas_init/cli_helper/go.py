import logging
import os
from pathlib import Path

import dotenv

from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.settings.config import TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def run_go_tests(
    repo_path: Path,
    repo_alias: str,
    package_prefix: str,
    settings: AtlasInitSettings,
    groups: list[TestSuite],
):
    env_vars_vs_code = settings.env_vars_vs_code
    if not env_vars_vs_code.exists():
        logger.warning(f"no env vars found @ {env_vars_vs_code}")
    test_env = os.environ | dotenv.dotenv_values(env_vars_vs_code)
    ci_value = test_env.pop("CI", None)
    if ci_value:
        logger.warning(f"pooped CI={ci_value}")
    env_keys_set = sorted(test_env)
    logger.info(f"go test keys: {env_keys_set}")
    for group in groups:
        packages = ",".join(f"{package_prefix}/{pkg}" for pkg in group.repo_go_packages.get(repo_alias, []))
        if not packages:
            logger.warning(f"no go packages for suite: {group}")
            continue
        command = f"go test {packages} -v -run ^TestAcc* -timeout 300m".split(" ")
        if not group.sequential_tests:
            command.extend(["-parallel", "20"])
        is_ok = run_command_is_ok(command, test_env, cwd=repo_path, logger=logger)
        assert is_ok, f"go tests failed for {group}"
