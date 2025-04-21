import logging
import os
import re
from pathlib import Path

import typer
from model_lib import Entity
from pydantic import Field
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.cli_cfn.files import create_sample_file_from_input
from atlas_init.cli_helper.run import (
    run_binary_command_is_ok,
)
from atlas_init.cli_helper.run_manager import RunManager
from atlas_init.cli_root import is_dry_run
from atlas_init.repos.path import Repo, ResourcePaths, find_paths
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings
from atlas_init.settings.env_vars_generated import AWSSettings

logger = logging.getLogger(__name__)


class RunContractTest(Entity):
    resource_path: Path
    repo_path: Path
    cfn_region: str
    aws_profile: str
    skip_build: bool = False
    dry_run: bool = Field(default_factory=is_dry_run)
    only_names: list[str] | None = None

    @property
    def run_tests_command(self) -> tuple[str, str]:
        if self.only_names:
            names = " ".join(f"-k {name}" for name in self.only_names)
            return (
                "cfn",
                f"test --function-name TestEntrypoint --verbose --region {self.cfn_region} -- {names}",
            )
        return (
            "cfn",
            f"test --function-name TestEntrypoint --verbose --region {self.cfn_region}",
        )


class RunContractTestOutput(Entity):
    sam_local_logs: str
    sam_local_exit_code: int
    contract_test_ok: bool
    rpdk_log: str


class CreateContractTestInputs(Entity):
    resource_path: Path
    log_group_name: str


class CFNBuild(Entity):
    resource_path: Path
    dry_run: bool = Field(default_factory=is_dry_run)
    is_debug: bool = False
    tags: str = "logging callback metrics scheduler"
    cgo: int = 0
    goarch: str = "amd64"
    goos: str = "linux"
    git_sha: str = "local"
    ldflags: str = "-s -w -X github.com/mongodb/mongodbatlas-cloudformation-resources/util.defaultLogLevel=info -X github.com/mongodb/mongodbatlas-cloudformation-resources/version.Version=${CFNREP_GIT_SHA}"

    @property
    def extra_env(self) -> dict[str, str]:
        return {"GOOS": self.goos, "CGO_ENABLED": str(self.cgo), "GOARCH": self.goarch}

    @property
    def flags(self) -> str:
        return self.ldflags.replace("${CFNREP_GIT_SHA}", self.git_sha)

    @property
    def command_build(self) -> str:
        return f'build -ldflags="{self.flags}" -tags="{self.tags}" -o bin/bootstrap cmd/main.go'

    @property
    def cfn_generate(self) -> str:
        return "generate"

    @property
    def commands(self) -> list[tuple[str, str]]:
        return [
            ("cfn", self.cfn_generate),
            ("go", self.command_build),
        ]


def contract_test_cmd(
    only_names: list[str] = typer.Option(None, "-n", "--only-names", help="only run these contract tests"),
):
    result = contract_test(only_names=only_names)
    if result.contract_test_ok:
        logger.info("contract tests passed 🥳")
    else:
        logger.error("contract tests failed 💥")
        logger.error(
            f"function logs (exit_code={result.sam_local_exit_code}):\n {result.sam_local_logs}\n\nRPDK logs:\n{result.rpdk_log[-10_000:]}"
        )
        raise typer.Exit(1)
    return result


def contract_test(
    settings: AtlasInitSettings | None = None,
    resource_paths: ResourcePaths | None = None,
    only_names: list[str] | None = None,
):
    settings = settings or init_settings(AWSSettings)
    resource_paths = resource_paths or find_paths(Repo.CFN)
    resource_name = resource_paths.resource_name
    create_inputs = CreateContractTestInputs(
        resource_path=resource_paths.resource_path,
        log_group_name=f"mongodb-atlas-{resource_name}-logs",
    )
    create_response = create_contract_test_inputs(create_inputs)
    create_response.log_input_files(logger)
    aws_settings = AWSSettings.from_env()
    run_contract_test = RunContractTest(
        resource_path=resource_paths.resource_path,
        repo_path=resource_paths.repo_path,
        aws_profile=aws_settings.AWS_PROFILE,
        cfn_region=settings.cfn_region(aws_settings.AWS_REGION),
        only_names=only_names,
    )
    if run_contract_test.skip_build:
        logger.info("skipping build")
    else:
        build_event = CFNBuild(resource_path=resource_paths.resource_path)
        build(build_event)
        logger.info("build ok ✅")
    return run_contract_tests(run_contract_test)


class CreateContractTestInputsResponse(Entity):
    input_files: list[Path]
    sample_files: list[Path]

    def log_input_files(self, logger: logging.Logger):
        inputs = self.input_files
        if not inputs:
            logger.warning("no input files created")
            return
        inputs_dir = self.input_files[0].parent
        logger.info(f"{len(inputs)} inputs created in '{inputs_dir}'")
        logger.info("\n".join(f"'{file.name}'" for file in self.input_files))


def create_contract_test_inputs(
    event: CreateContractTestInputs,
) -> CreateContractTestInputsResponse:
    inputs_dir = event.resource_path / "inputs"
    samples_dir = event.resource_path / "samples"
    test_dir = event.resource_path / "test"
    sample_files = []
    input_files = []
    for template in sorted(test_dir.glob("*.template.json")):
        template_file = template.read_text()
        template_file = file_replacements(template_file, template.name)
        inputs_file = inputs_dir / template.name.replace(".template", "")
        ensure_parents_write_text(inputs_file, template_file)
        input_files.append(inputs_file)
        sample_file = create_sample_file_from_input(samples_dir, event.log_group_name, inputs_file)
        sample_files.append(sample_file)
    return CreateContractTestInputsResponse(input_files=input_files, sample_files=sample_files)


def file_replacements(text: str, file_name: str) -> str:
    for match in re.finditer(r"\${(\w+)}", text):
        var_name = match.group(1)
        if env_value := os.environ.get(var_name):
            text = text.replace(match.group(0), env_value)
        else:
            logger.warning(f"found placeholder {match.group(0)} in {file_name} but no replacement")
    return text


def build(event: CFNBuild):
    for binary, command in event.commands:
        is_ok = run_binary_command_is_ok(
            binary,
            command,
            cwd=event.resource_path,
            logger=logger,
            dry_run=event.dry_run,
            env={**os.environ, **event.extra_env},
        )
        if not is_ok:
            logger.critical(f"failed to run {binary} {command}")
            raise typer.Exit(1)


def run_contract_tests(event: RunContractTest) -> RunContractTestOutput:
    with RunManager(dry_run=event.dry_run) as manager:
        manager.set_timeouts(3)
        resource_path = event.resource_path
        run_future = manager.run_process_wait_on_log(
            f"local start-lambda --skip-pull-image --region {event.cfn_region}",
            binary="sam",
            cwd=resource_path,
            logger=logger,
            line_in_log="Running on http://",
            timeout=60,
        )
        binary, test_cmd = event.run_tests_command
        test_result_ok = run_binary_command_is_ok(
            binary,
            test_cmd,
            cwd=resource_path,
            logger=logger,
            dry_run=event.dry_run,
        )
        extra_log = resource_path / "rpdk.log"
        log_content = extra_log.read_text() if extra_log.exists() else ""
    sam_local_result = run_future.result(timeout=1)
    return RunContractTestOutput(
        sam_local_logs=sam_local_result.result_str,
        sam_local_exit_code=sam_local_result.exit_code or -1,
        contract_test_ok=test_result_ok,
        rpdk_log=log_content,
    )
