import logging
from typing import Type, TypeVar

from click.testing import Result
from model_lib import copy_and_validate
from typer.testing import CliRunner

from atlas_init.cli import app
from atlas_init.settings.env_vars import (
    ENV_PROFILE,
    ENV_PROJECT_NAME,
    REQUIRED_FIELDS,
    AtlasInitPaths,
    EnvVarsError,
    init_settings,
)
from test_atlas_init.conftest import write_required_vars

runner = CliRunner()
logger = logging.getLogger(__name__)


def run(command: str, exit_code: int = 0) -> Result:
    result = runner.invoke(app, command.split())
    logger.info(f"cli command output={result.stdout}")
    if exit_code == 0 and (e := result.exception):
        logger.exception(e)
        raise e
    assert result.exit_code == exit_code, "exit code is not as expected"
    return result


ErrT = TypeVar("ErrT", bound=Exception)


def run_expect_error(command: str, error: Type[ErrT], exit_code: int = 1) -> ErrT:
    result = run(command, exit_code=exit_code)
    assert isinstance(result.exception, error)
    return result.exception


def test_normal_help_command_is_ok():
    run("--help", exit_code=0)


def test_missing_env_vars(tmp_paths):
    error = run_expect_error("init", error=EnvVarsError)
    assert error.missing == REQUIRED_FIELDS


def test_missing_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    error = run_expect_error("init", error=EnvVarsError)
    assert ENV_PROJECT_NAME in error.missing


def test_cli_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    name = test_cli_project_name.__name__
    run(f"--project {name} cfn")
    assert init_settings().project_name == name


def test_override_profile_with_env_var(tmp_paths, monkeypatch):
    different_profile = "other-profile"
    monkeypatch.setenv(ENV_PROFILE, different_profile)
    new_paths = copy_and_validate(tmp_paths, profile=different_profile)
    project_name = "some-project"
    write_required_vars(new_paths, project_name=project_name)
    run("cfn")

    settings = init_settings()
    assert settings.profile == different_profile
    assert settings.project_name == project_name


def test_override_profile_with_cli(tmp_paths):
    different_profile = "cli-profile"
    new_paths = copy_and_validate(tmp_paths, profile=different_profile)
    project_name = test_override_profile_with_cli.__name__
    write_required_vars(new_paths, project_name=project_name)

    run(f"--profile {different_profile} cfn")
    settings = init_settings()
    assert settings.profile == different_profile
    assert settings.project_name == project_name


def test_destroy_no_state_dir(tmp_paths: AtlasInitPaths, caplog):
    assert not tmp_paths.tf_state_path.exists()
    caplog.set_level(logging.INFO)
    write_required_vars(tmp_paths, project_name=test_destroy_no_state_dir.__name__)
    run("destroy")
    messages = caplog.messages
    assert any("no terraform state found" in message for message in messages)
