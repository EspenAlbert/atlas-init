import logging
import re
from pathlib import Path

from model_lib import Entity
from pydantic import Field
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.cli_cfn.files import create_sample_file_from_input
from atlas_init.cli_helper.run import run_command_exit_on_failure, run_command_is_ok
from atlas_init.cli_helper.run_manager import RunManager
from atlas_init.cli_root import is_dry_run
from atlas_init.repos.path import Repo, ResourcePaths, find_paths
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings

logger = logging.getLogger(__name__)


class RunContractTest(Entity):
    resource_path: Path
    repo_path: Path
    cfn_region: str
    aws_profile: str
    skip_build: bool = False
    dry_run: bool = Field(default_factory=is_dry_run)


class RunContractTestOutput(Entity):
    sam_local_logs: str
    sam_local_exit_code: int
    contract_test_ok: bool


class CreateContractTestInputs(Entity):
    resource_path: Path
    env_vars_generated: dict[str, str]
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
    def flags(self) -> str:
        return self.ldflags.replace("${CFNREP_GIT_SHA}", self.git_sha)

    @property
    def command(self) -> str:
        return f'env GOOS={self.goos} CGO_ENABLED={self.cgo} GOARCH={self.goarch} go build -ldflags="{self.flags}" -tags="{self.tags}" -o bin/bootstrap cmd/main.go'

    @property
    def cfn_generate(self) -> str:
        return "cfn generate"

    @property
    def commands(self) -> list[str]:
        return [self.cfn_generate, self.command]


def contract_test(
    settings: AtlasInitSettings | None = None,
    resource_paths: ResourcePaths | None = None,
):
    settings = settings or init_settings()
    resource_paths = resource_paths or find_paths(Repo.CFN)
    resource_name = resource_paths.resource_name
    generated_env_vars = settings.load_env_vars_generated()
    create_inputs = CreateContractTestInputs(
        resource_path=resource_paths.resource_path,
        env_vars_generated=generated_env_vars,
        log_group_name=f"mongodb-atlas-{resource_name}-logs",
    )
    create_response = create_contract_test_inputs(create_inputs)
    create_response.log_input_files(logger)
    run_contract_test = RunContractTest(
        resource_path=resource_paths.resource_path,
        repo_path=resource_paths.repo_path,
        aws_profile=settings.AWS_PROFILE,
        cfn_region=settings.cfn_region,
    )
    if run_contract_test.skip_build:
        logger.info("skipping build")
    else:
        build_event = CFNBuild(resource_path=resource_paths.resource_path)
        build(build_event)
        logger.info("build ok ✅")
    result = run_contract_tests(run_contract_test)
    if result.contract_test_ok:
        logger.info("contract tests passed 🥳")
    else:
        logger.error("contract tests failed 💥")
        logger.error(f"function logs (exit_code={result.sam_local_exit_code}):\n {result.sam_local_logs}")


class CreateContractTestInputsResponse(Entity):
    input_files: list[Path]
    sample_files: list[Path]

    def log_input_files(self, logger: logging.Logger):
        inputs = self.input_files
        if not inputs:
            logger.warning("no input files created")
            return
        inputs_dir = self.input_files[0].parent
        logger.info(f"{len(inputs)} created in '{inputs_dir}'")
        for file in self.input_files:
            logger.info(file.name)


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
        template_file = file_replacements(template_file, event.env_vars_generated, template.name)
        inputs_file = inputs_dir / template.name.replace(".template", "")
        ensure_parents_write_text(inputs_file, template_file)
        input_files.append(inputs_file)
        sample_file = create_sample_file_from_input(samples_dir, event.log_group_name, inputs_file)
        sample_files.append(sample_file)
    return CreateContractTestInputsResponse(input_files=input_files, sample_files=sample_files)


def file_replacements(text: str, replacements: dict[str, str], file_name: str) -> str:
    for match in re.finditer(r"\${(\w+)}", text):
        var_name = match.group(1)
        if var_name in replacements:
            text = text.replace(match.group(0), replacements[var_name])
        else:
            logger.warning(f"found placeholder {match.group(0)} in {file_name} but no replacement")
    return text


def build(event: CFNBuild):
    for command in event.commands:
        run_command_exit_on_failure(command, cwd=event.resource_path, logger=logger, dry_run=event.dry_run)


def run_contract_tests(event: RunContractTest) -> RunContractTestOutput:
    with RunManager(dry_run=event.dry_run) as manager:
        resource_path = event.resource_path
        run_future = manager.run_process_wait_on_log(
            f"sam local start-lambda --skip-pull-image --region {event.cfn_region}",
            cwd=resource_path,
            logger=logger,
            line_in_log="Running on http://",
            timeout=60,
        )
        contract_test = f"cfn test --function-name TestEntrypoint --verbose --region {event.cfn_region}"
        test_result_ok = run_command_is_ok(
            contract_test.split(),
            cwd=resource_path,
            logger=logger,
            env={"AWS_PROFILE": event.aws_profile},
            dry_run=event.dry_run,
        )
    sam_local_result = run_future.result(timeout=1)
    return RunContractTestOutput(
        sam_local_logs=sam_local_result.result_str,
        sam_local_exit_code=sam_local_result.exit_code or -1,
        contract_test_ok=test_result_ok,
    )
