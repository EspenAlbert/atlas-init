import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, TypeAlias
from unittest.mock import MagicMock

import pytest
from _pytest.python import CallSpec2
from model_lib import dump, field_names
from pydantic import BaseModel, Field
from zero_3rdparty.file_utils import copy, ensure_parents_write_text

from atlas_init.cli_args import ENV_VAR_SDK_REPO_PATH
from atlas_init.cli_helper.run import LOG_CMD_PREFIX
from atlas_init.cli_root import set_dry_run
from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.repos.path import (
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    Repo,
    resource_root,
)
from atlas_init.settings.env_vars import (
    ENV_PROJECT_NAME,
    AtlasInitSettings,
)
from atlas_init.settings.env_vars_generated import AtlasSettings
from atlas_init.settings.path import current_dir, dump_dotenv
from atlas_init.tf_ext.settings import TfExtSettings

logger = logging.getLogger(__name__)
REQUIRED_FIELDS = [
    "MONGODB_ATLAS_BASE_URL",
    "MONGODB_ATLAS_ORG_ID",
    "MONGODB_ATLAS_PRIVATE_KEY",
    "MONGODB_ATLAS_PUBLIC_KEY",
]
REPO_PATH = Path(__file__).parent.parent


def _fixture_has_skip_marker(fixture_name: str, fixture_def) -> bool:
    markers = getattr(fixture_def.func, "pytestmark", [])
    return any(marker.name.startswith("skip") for marker in markers)


def pytest_collection_modifyitems(config, items):
    """Skip tests that are marked with @pytest.mark.skip
    To avoid the terminal session in VS Code that might have extra env-vars set accidentally run marked tests"""
    skip_marked_tests = os.getenv("SKIP_MARKED_TESTS", "false").lower() in ("true", "1", "yes")
    if not skip_marked_tests:
        return
    for item in items:
        if any(marker.name.startswith("skip") for marker in item.own_markers):
            item.add_marker(pytest.mark.skip(reason="Skipping test due to SKIP_MARKED_TESTS environment variable"))
            continue
        item_session: pytest.Session = item.session
        fixture_manager = item_session._fixturemanager
        call_spec: CallSpec2 | None = getattr(item, "callspec", None)
        for fixture_name in item.fixturenames:
            if fixture_name == "request" or call_spec and fixture_name in call_spec.params:
                continue
            fixturedefs: list = fixture_manager.getfixturedefs(fixture_name, item)  # type: ignore
            if not fixturedefs:
                logger.warning(f"No fixture definitions found for {fixture_name} in {item}")
                continue
            assert len(fixturedefs) == 1, f"Expected one fixture definition for {fixture_name}, got {len(fixturedefs)}"
            if _fixture_has_skip_marker(fixture_name, fixturedefs[0]):
                item.add_marker(
                    pytest.mark.skip(reason=f"Skipping test due to fixture {fixture_name} having skip marker")
                )
                break


@pytest.fixture(
    autouse=True, scope="function"
)  # autouse to avoid any test modifying the os.environ and leaving side effects for next test
def settings(monkeypatch, tmp_path: Path) -> AtlasInitSettings:  # type: ignore
    env_before = {**os.environ}
    if existing_in_env := {key: os.environ[key] for key in REQUIRED_FIELDS if key in os.environ}:
        for k, v in existing_in_env.items():
            logger.warning(f"Environment variables already set: {k}={v}")
    static_dir = tmp_path / "static"
    monkeypatch.setenv("STATIC_DIR", str(static_dir))
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))
    static_dir.mkdir()
    cache_dir.mkdir()
    yield AtlasInitSettings.from_env()  # type: ignore
    os.environ.clear()
    os.environ.update(env_before)


@pytest.fixture()
def tf_ext_settings_repo_path(settings, monkeypatch) -> TfExtSettings:
    repo_path = Path(__file__).parent.parent
    static_dir = repo_path / "static"
    monkeypatch.setenv("STATIC_DIR", str(static_dir))
    cache_dir = repo_path / "cache"
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))
    static_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)
    settings.STATIC_DIR = static_dir
    settings.CACHE_DIR = cache_dir
    return TfExtSettings.from_env()


@pytest.fixture()
def api_spec_path_transformed() -> Path:
    return resolve_admin_api_path(os.environ.get(ENV_VAR_SDK_REPO_PATH, ""), "main", "")


BaseDir: TypeAlias = Literal["cwd"]


@dataclass
class FileAssertion:
    base: BaseDir = "cwd"
    glob: str = ""
    rglob: str = ""

    def __post_init__(self):
        if self.glob and self.rglob:
            raise ValueError("cannot have both glob and rglob")
        if not self.glob and not self.rglob:
            raise ValueError("must have one of glob or rglob")


@dataclass
class RunAssertion:
    substring: str


@dataclass
class CLIArgs:
    project_name: str = ""  # default to current test name
    repo: Repo | None = None
    cfn_resource_name: str = ""
    env_vars_in_file: dict[str, str] = field(default_factory=dict)
    settings: list[BaseModel] = field(default_factory=list)
    aws_profile: str = ""
    is_dry_run: bool = True
    skip_generated_vars: bool = False

    commands_expected: list[str] = field(default_factory=list)
    files_glob_expected: list[str] = field(default_factory=list)
    assertions: list[FileAssertion | RunAssertion] = field(default_factory=list)

    def __post_init__(self):
        for each_settings in self.settings:
            self.env_vars_in_file |= each_settings.model_dump()
        if self.aws_profile != "":
            self.env_vars_in_file["AWS_PROFILE"] = self.aws_profile
        if self.is_dry_run:
            self.env_vars_in_file |= mongodb_atlas_required_vars()
        if self.commands_expected:
            self.assertions.extend([RunAssertion(command) for command in self.commands_expected])
        if self.files_glob_expected:
            self.assertions.extend([FileAssertion(glob=glob) for glob in self.files_glob_expected])


class _AssertionOutput(BaseModel):
    commands_missing: list[str] = Field(default_factory=list)
    files_missing: list[str] = Field(default_factory=list)
    commands_run: dict[str, str] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)


def extract_node_subdir(node_name: str) -> str:
    """
    >>> extract_node_subdir("test_contract_test[trigger]")
    'trigger'
    >>> extract_node_subdir("test_contract_test")
    ''
    """
    return node_name.split("[", 1)[1].split("]")[0] if "[" in node_name else ""


class ConfigureSignature(Protocol):
    def __call__(self, args: CLIArgs | None = None) -> AtlasInitSettings: ...


@pytest.fixture
def cli_configure(
    original_datadir: Path, request, monkeypatch, tmp_path, settings: AtlasInitSettings
) -> ConfigureSignature:
    def _cli_configure(
        args: CLIArgs | None = None,
    ) -> AtlasInitSettings:
        args = args or CLIArgs()
        set_dry_run(args.is_dry_run)
        function_name = request.function.__name__
        if not args.project_name:
            args.project_name = function_name
        write_required_vars(settings, args.env_vars_in_file, args.project_name)
        if not args.skip_generated_vars:
            write_generated_vars(settings, args.env_vars_in_file)
        repo = args.repo
        if repo is None:
            return settings
        if repo != Repo.CFN:
            raise NotImplementedError(f"repo: {repo}")
        repo_path = tmp_path / Repo.CFN
        git_dir: Path = repo_path / ".git"
        git_dir.mkdir(parents=True)
        mocked_git_repo = MagicMock(
            remotes=[
                MagicMock(
                    name="origin",
                    urls=[f"https://github.com/{GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES}"],
                )
            ],
        )
        monkeypatch.setattr("atlas_init.repos.path._GitRepo", lambda _: mocked_git_repo)
        cwd = repo_path
        if cfn_resource_name := args.cfn_resource_name:
            cwd = cfn_resource_path(repo_path, cfn_resource_name)
            node_name: str = request.node.name
            if subdir := extract_node_subdir(node_name):
                copy(original_datadir / subdir, cwd)
            ensure_parents_write_text(cwd / "cmd/main.go", "")
        monkeypatch.chdir(cwd)
        return settings

    return _cli_configure


@pytest.fixture
def cli_assertions(file_regression, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)

    def normalize_cmd(substring_match: str, text: str) -> str:
        text = text.removeprefix(LOG_CMD_PREFIX)
        text = text.replace(str(tmp_path), "/tmp")
        binary = substring_match.split()[0]
        if not text.startswith(substring_match):
            binary_path_pattern = re.compile(rf"(\S+/)({binary})")
            text = binary_path_pattern.sub(r"\2", text, count=1)
        return text

    def _check_assertions(args: CLIArgs):
        output = _AssertionOutput()
        for assertion in args.assertions:
            match assertion:
                case RunAssertion(substring):
                    for log_text in caplog.messages:
                        if substring in log_text:
                            output.commands_run[substring] = normalize_cmd(substring, log_text)
                            break
                    else:
                        output.commands_missing.append(f"substring no match: {substring}")
                case FileAssertion(base, glob, rglob):
                    if base != "cwd":
                        raise NotImplementedError(f"base: {base}")
                    cwd = current_dir()
                    files = sorted(cwd.glob(glob)) if glob else sorted(cwd.rglob(rglob))
                    if not files:
                        output.files_missing.append(f"no files found in {base}: {glob or rglob}")
                    output.files |= {str(file.relative_to(cwd)): file.read_text() for file in files}
        yaml_text = dump(output, "yaml")
        file_regression.check(yaml_text, extension=".yaml")
        assert output.commands_missing == [], output.commands_missing
        assert output.files_missing == [], output.files_missing

    return _check_assertions


def mongodb_atlas_required_vars() -> dict[str, str]:
    return {key: f"value_{key}" for key in field_names(AtlasSettings)}


def write_required_vars(
    paths: AtlasInitSettings,
    env_vars_in_file: dict[str, str] | None = None,
    project_name: str = "",
):
    env_vars_in_file = env_vars_in_file or mongodb_atlas_required_vars()
    if project_name:
        env_vars_in_file[ENV_PROJECT_NAME] = project_name
    dump_dotenv(paths.env_file_manual, env_vars_in_file)


def write_generated_vars(paths: AtlasInitSettings, env_vars_in_file: dict[str, str]):
    dump_dotenv(paths.env_vars_generated, env_vars_in_file)
    dump_dotenv(paths.env_vars_vs_code, env_vars_in_file)


def cfn_resource_path(repo_path: Path, resource_name: str) -> Path:
    root = resource_root(repo_path)
    return root / resource_name


@pytest.fixture()
@pytest.mark.skipif(os.environ.get("TF_REPO_PATH", "") == "", reason="needs os.environ[TF_REPO_PATH]")
def tf_repo_path() -> Path:
    tf_repo_path = Path(os.environ["TF_REPO_PATH"])
    assert tf_repo_path.exists(), f"TF_REPO_PATH does not exist: {tf_repo_path}"
    return tf_repo_path
