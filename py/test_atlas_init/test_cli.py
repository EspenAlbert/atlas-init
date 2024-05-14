from atlas_init.cli import app
from typer.testing import CliRunner

from atlas_init.settings.env_vars import init_settings
from test_atlas_init.conftest import write_required_vars

runner = CliRunner()


def test_normal_help_command_is_ok():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_missing_env_vars(tmp_paths):
    result = runner.invoke(app, ["cfn"])
    assert (
        "missing env_vars: ['ATLAS_INIT_PROJECT_NAME', 'MONGODB_ATLAS_ORG_ID', 'MONGODB_ATLAS_PRIVATE_KEY', 'MONGODB_ATLAS_PUBLIC_KEY'"
        in result.stdout
    )
    assert result.exit_code == 1


def test_missing_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    result = runner.invoke(app, ["cfn"])

    assert "missing env_vars: ['ATLAS_INIT_PROJECT_NAME']" in result.stdout
    assert result.exit_code == 1


def test_cli_project_name(tmp_paths):
    write_required_vars(tmp_paths)
    name = test_cli_project_name.__name__
    result = runner.invoke(app, ["--project", name, "cfn"])
    assert result.exit_code == 0
    assert init_settings().project_name == name
