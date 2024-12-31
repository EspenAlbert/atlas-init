from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
from typing import Callable, Literal, TypeAlias
from unittest.mock import MagicMock

from atlas_init.cli_helper.run import LOG_CMD_PREFIX
from atlas_init.cli_root import set_dry_run
from atlas_init.repos.path import (
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    Repo,
    resource_root,
)
from model_lib import dump
from pydantic import BaseModel, Field
import pytest

from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.settings.env_vars import (
    ENV_PROFILES_PATH,
    ENV_PROJECT_NAME,
    REQUIRED_FIELDS,
    AtlasInitPaths,
)
from atlas_init.settings.path import current_dir, dump_dotenv
from zero_3rdparty.file_utils import copy, ensure_parents_write_text


@pytest.fixture
def tmp_paths(monkeypatch, tmp_path: Path) -> AtlasInitPaths:  # type: ignore
    env_before = {**os.environ}
    monkeypatch.setenv(ENV_PROFILES_PATH, str(tmp_path))
    yield AtlasInitPaths()  # type: ignore
    os.environ.clear()
    os.environ.update(env_before)


@pytest.fixture(scope="session")
def api_spec_path_transformed() -> Path:
    return resolve_admin_api_path(os.environ.get("SDK_REPO_PATH", ""), "main", "")


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
            self.assertions.extend(
                [RunAssertion(command) for command in self.commands_expected]
            )
        if self.files_glob_expected:
            self.assertions.extend(
                [FileAssertion(glob=glob) for glob in self.files_glob_expected]
            )


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


@pytest.fixture()
def cli_configure(
    original_datadir: Path, request, monkeypatch, tmp_path, tmp_paths: AtlasInitPaths
) -> Callable[[CLIArgs], None]:
    def _cli_configure(
        args: CLIArgs,
    ):
        set_dry_run(args.is_dry_run)
        function_name = request.function.__name__
        if not args.project_name:
            args.project_name = function_name
        write_required_vars(tmp_paths, args.env_vars_in_file, args.project_name)
        if not args.skip_generated_vars:
            write_generated_vars(tmp_paths, args.env_vars_in_file)
        repo = args.repo
        if repo is None:
            return
        if repo != Repo.CFN:
            raise NotImplementedError(f"repo: {repo}")
        repo_path = tmp_path / Repo.CFN
        git_dir: Path = repo_path / ".git"
        git_dir.mkdir(parents=True)
        mocked_git_repo = MagicMock(
            remotes=[
                MagicMock(
                    name="origin",
                    urls=[
                        f"https://github.com/{GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES}"
                    ],
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

    return _cli_configure


@pytest.fixture()
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
                        output.commands_missing.append(
                            f"substring no match: {substring}"
                        )
                case FileAssertion(base, glob, rglob):
                    if base != "cwd":
                        raise NotImplementedError(f"base: {base}")
                    cwd = current_dir()
                    files = sorted(cwd.glob(glob)) if glob else sorted(cwd.rglob(rglob))
                    if not files:
                        output.files_missing.append(
                            f"no files found in {base}: {glob or rglob}"
                        )
                    output.files |= {
                        str(file.relative_to(cwd)): file.read_text() for file in files
                    }
        yaml_text = dump(output, "yaml")
        file_regression.check(yaml_text, extension=".yaml")
        assert output.commands_missing == [], output.commands_missing
        assert output.files_missing == [], output.files_missing

    return _check_assertions


def mongodb_atlas_required_vars() -> dict[str, str]:
    return {key: f"value_{key}" for key in REQUIRED_FIELDS}


def write_required_vars(
    paths: AtlasInitPaths,
    env_vars_in_file: dict[str, str] | None = None,
    project_name: str = "",
):
    env_vars_in_file = env_vars_in_file or mongodb_atlas_required_vars()
    if project_name:
        env_vars_in_file[ENV_PROJECT_NAME] = project_name
    dump_dotenv(paths.env_file_manual, env_vars_in_file)


def write_generated_vars(paths: AtlasInitPaths, env_vars_in_file: dict[str, str]):
    dump_dotenv(paths.env_vars_generated, env_vars_in_file)
    dump_dotenv(paths.env_vars_vs_code, env_vars_in_file)


def cfn_resource_path(repo_path: Path, resource_name: str) -> Path:
    root = resource_root(repo_path)
    return root / resource_name
