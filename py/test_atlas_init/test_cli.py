import logging

from click.testing import Result
from model_lib import copy_and_validate
from typer.testing import CliRunner

from atlas_init.cli import app
from atlas_init.settings.env_vars import (
    AtlasInitPaths,
    as_env_var_name,
    init_settings,
)
from test_atlas_init.conftest import write_required_vars

runner = CliRunner()
logger = logging.getLogger(__name__)


def run(command: str, exit_code: int = 0) -> Result:
    result = runner.invoke(app, command.split())
    logger.info(result.stdout)
    if exit_code == 0 and (e := result.exception):
        logger.exception(e)
        raise e
    assert result.exit_code == exit_code, "exit code is not as expected"
    return result


def run_expect_error(command: str, error_message: str, exit_code: int = 1) -> Result:
    result = run(command, exit_code=exit_code)
    assert error_message in result.stdout
    return result


def test_normal_help_command_is_ok():
    run("--help", exit_code=0)


def test_missing_env_vars(tmp_paths):
    run_expect_error(
        "init",
        "missing env_vars: ['ATLAS_INIT_PROJECT_NAME', 'MONGODB_ATLAS_ORG_ID', 'MONGODB_ATLAS_PRIVATE_KEY', 'MONGODB_ATLAS_PUBLIC_KEY'",
    )


def test_missing_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    run_expect_error("init", "missing env_vars: ['ATLAS_INIT_PROJECT_NAME']")


def test_cli_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    name = test_cli_project_name.__name__
    run(f"--project {name} cfn")
    assert init_settings().project_name == name


def test_override_profile_with_env_var(tmp_paths, monkeypatch):
    different_profile = "other-profile"
    monkeypatch.setenv(as_env_var_name("profile"), different_profile)
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
