import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait
from enum import StrEnum
from pathlib import Path

from model_lib import Entity
from pydantic import Field

from atlas_init.cli_helper.run import run_command_is_ok_output
from atlas_init.cli_tf.go_test_run import (
    GoTestRun,
    parse_tests,
)
from atlas_init.settings.config import TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings
from atlas_init.settings.path import load_dotenv

logger = logging.getLogger(__name__)


class GoTestMode(StrEnum):
    package = "package"
    individual = "individual"
    regex = "regex"


class GoEnvVars(StrEnum):
    manual = "manual"
    vscode = "vscode"


class GoTestCaptureMode(StrEnum):
    capture = "capture"
    replay = "replay"
    replay_and_update = "replay-and-update"
    no_capture = "no-capture"


def env_vars_for_capture(mode: GoTestCaptureMode) -> dict[str, str]:
    env = {}
    if mode == GoTestCaptureMode.capture:
        env["HTTP_MOCKER_CAPTURE"] = "true"
    if mode in {GoTestCaptureMode.replay, GoTestCaptureMode.replay_and_update}:
        env["HTTP_MOCKER_REPLAY"] = "true"
    if mode == GoTestCaptureMode.replay_and_update:
        env["HTTP_MOCKER_DATA_UPDATE"] = "true"
    return env


class GoTestResult(Entity):
    logs_dir: Path
    runs: dict[str, list[GoTestRun]] = Field(default_factory=dict)
    failure_names: set[str] = Field(default_factory=set)

    test_name_package_path: dict[str, Path] = Field(default_factory=dict)

    def add_test_package_path(self, test_name: str, package_path: Path):
        if old_path := self.test_name_package_path.get(test_name):
            logger.warning(f"overwriting test_name={test_name} with package_path={old_path} --> {package_path}")
        self.test_name_package_path[test_name] = package_path

    def add_test_results_all_pass(self, test_name: str, test_results: list[GoTestRun]) -> bool:
        prev_test_results = self.runs.setdefault(test_name, [])
        if prev_test_results:
            logger.warning(f"2nd time test results for {test_name}")
        for result in test_results:
            log_path = _log_path(self.logs_dir, test_name)
            result.log_path = log_path
        prev_test_results.extend(test_results)
        return all(run.is_pass for run in test_results)


def run_go_tests(
    repo_path: Path,
    settings: AtlasInitSettings,
    groups: list[TestSuite],  # type: ignore
    mode: GoTestMode | str = GoTestMode.package,
    *,
    dry_run: bool = False,
    timeout_minutes: int = 300,
    concurrent_runs: int = 20,
    re_run: bool = False,
    env_vars: GoEnvVars = GoEnvVars.vscode,
    names: set[str] | None = None,
    capture_mode: GoTestCaptureMode = GoTestCaptureMode.capture,
    use_old_schema: bool = False,
) -> GoTestResult:
    test_env = resolve_env_vars(
        settings,
        env_vars,
        capture_mode=capture_mode,
        use_old_schema=use_old_schema,
    )
    if ci_value := test_env.pop("CI", None):
        logger.warning(f"popped CI={ci_value}")
    logs_dir = settings.go_test_logs_dir
    results = GoTestResult(logs_dir=logs_dir)
    commands_to_run: dict[str, str] = {}
    for group in groups:
        if group.sequential_tests:
            logger.info(f"running individual tests sequentially as {group.name} is set to sequential_tests")
            concurrent_runs = 1
        group_commands_to_run = group_commands_for_mode(
            repo_path, mode, concurrent_runs, timeout_minutes, names, results, group
        )
        if not group_commands_to_run:
            logger.warning(f"no tests for suite: {group.name}")
            continue
        commands_to_run |= group_commands_to_run
    commands_str = "\n".join(f"'{name}': '{command}'" for name, command in sorted(commands_to_run.items()))
    logger.info(f"will run the following commands:\n{commands_str}")
    if dry_run:
        return results
    if not commands_to_run:
        logger.warning("no tests to run!")
        return results
    return _run_tests(
        results,
        repo_path,
        logs_dir,
        commands_to_run,
        test_env,
        test_timeout_s=timeout_minutes * 60,
        max_workers=concurrent_runs,
        re_run=re_run,
    )


def group_commands_for_mode(
    repo_path: Path,
    mode: GoTestMode | str,
    concurrent_runs: int,
    timeout_minutes: int,
    names: set[str] | None,
    results: GoTestResult,
    group: TestSuite,  # type: ignore
) -> dict[str, str]:
    commands_to_run: dict[str, str] = {}
    if mode == GoTestMode.package:
        name_regex = f"^({'|'.join(names)})$" if names else "^TestAcc*"
        for pkg_url in group.package_url_tests(repo_path):
            command = f"go test {pkg_url} -v -run {name_regex} -timeout {timeout_minutes}m"
            if not group.sequential_tests:
                command = f"{command} -parallel {concurrent_runs}"
            pkg_name = pkg_url.rsplit("/")[-1]
            commands_to_run[f"{group.name}-{pkg_name}"] = command
        return commands_to_run
    if mode == GoTestMode.individual:
        prefix = "TestAcc"
    else:
        logger.info(f"using {GoTestMode.regex} with {mode}")
        prefix = mode
    for pkg_url, tests in group.package_url_tests(repo_path, prefix=prefix).items():
        for name, pkg_path in tests.items():
            if names and name not in names:
                continue
            results.add_test_package_path(name, pkg_path)
            commands_to_run[name] = f"go test {pkg_url} -v -run ^{name}$ -timeout {timeout_minutes}m"
    return commands_to_run


def resolve_env_vars(
    settings: AtlasInitSettings,
    env_vars: GoEnvVars,
    *,
    capture_mode: GoTestCaptureMode,
    use_old_schema: bool,
    skip_os: bool = False,
) -> dict[str, str]:
    if env_vars == GoEnvVars.manual:
        test_env_vars = settings.manual_env_vars
    elif env_vars == GoEnvVars.vscode:
        test_env_vars = load_dotenv(settings.env_vars_vs_code)
    else:
        raise NotImplementedError(f"don't know how to load env_vars={env_vars}")
    test_env_vars |= {
        "TF_ACC": "1",
        "TF_LOG": "DEBUG",
        "MONGODB_ATLAS_PREVIEW_PROVIDER_V2_ADVANCED_CLUSTER": ("false" if use_old_schema else "true"),
    }
    test_env_vars |= env_vars_for_capture(capture_mode)
    logger.info(f"go test env-vars-extra: {sorted(test_env_vars)}")
    if not skip_os:
        test_env_vars = os.environ | test_env_vars  # os.environ on the left side, prefer explicit args
    return test_env_vars


def _run_tests(
    results: GoTestResult,
    repo_path: Path,
    logs_dir: Path,
    commands_to_run: dict[str, str],
    test_env: dict[str, str],
    test_timeout_s: int = 301 * 60,
    max_workers: int = 2,
    *,
    re_run: bool = False,
) -> GoTestResult:
    futures = {}
    actual_workers = min(max_workers, len(commands_to_run)) or 1
    with ThreadPoolExecutor(max_workers=actual_workers) as pool:
        for name, command in sorted(commands_to_run.items()):
            log_path = _log_path(logs_dir, name)
            if log_path.exists() and log_path.read_text():
                if re_run:
                    logger.info(f"moving existing logs of {name} to old dir")
                    move_logs_to_dir(logs_dir, {name}, dir_name="old")
                else:
                    logger.info(f"skipping {name} because log exists")
                    continue
            command_env = {**test_env, "TF_LOG_PATH": str(log_path)}
            future = pool.submit(
                run_command_is_ok_output,
                command=command,
                env=command_env,
                cwd=repo_path,
                logger=logger,
            )
            futures[future] = name
        done, not_done = wait(futures.keys(), timeout=test_timeout_s)
        for f in not_done:
            logger.warning(f"timeout to run command name = {futures[f]}")
    for f in done:
        name: str = futures[f]
        try:
            ok, command_out = f.result()
        except Exception:
            logger.exception(f"failed to run command for {name}")
            results.failure_names.add(name)
            continue
        try:
            parsed_tests = parse_tests(command_out.splitlines())
        except Exception:
            logger.exception(f"failed to parse tests for {name}")
            results.failure_names.add(name)
            continue
        for test in parsed_tests:
            test.log_path = _log_path(logs_dir, name)
            # todo: possible add other fields
        if not parsed_tests and not ok:
            results.failure_names.add(name)
            logger.error(f"failed to run tests for {name}: {command_out}")
            continue
        if not parsed_tests:
            logger.warning(f"failed to parse tests for {name}: {command_out}")
            continue
        if not ok:
            logger.warning(f"failing tests for {name}: {command_out}")
        if not results.add_test_results_all_pass(name, parsed_tests):
            results.failure_names.add(name)
    if failure_names := results.failure_names:
        move_logs_to_dir(logs_dir, failure_names)
        logger.error(f"failed to run tests: {sorted(failure_names)}")
    return results


def move_logs_to_dir(logs_dir: Path, names: set[str], dir_name: str = "failures"):
    new_dir = logs_dir / dir_name
    for log in logs_dir.glob("*.log"):
        if log.stem in names:
            text = log.read_text()
            assert "\n" in text
            first_line = text.split("\n", maxsplit=1)[0]
            ts = first_line.split(" ")[0]
            log.rename(new_dir / f"{ts}.{log.name}")


def _log_path(logs_dir: Path, name: str) -> Path:
    return logs_dir / f"{name}.log"
