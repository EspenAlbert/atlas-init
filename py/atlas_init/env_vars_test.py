import dotenv
import pytest

from atlas_init.env_vars import (
    AtlasInitCommand,
    AtlasInitSettings,
    as_env_var_name,
    dump_manual_dotenv_from_env,
    validate_command_and_args,
)

C = AtlasInitCommand


@pytest.mark.parametrize(
    "command,extra_sys_args,expected_command,expected_args",
    [
        (None, [], C.INIT, []),
        (C.APPLY, [], C.APPLY, []),
        (C.APPLY, ["-auto-approve"], C.APPLY, ["-auto-approve"]),
    ],
)
def test_validate_command(command, extra_sys_args, expected_command, expected_args):
    command_args = [command] if command is not None else []
    actual_command, actual_args = validate_command_and_args(
        command, ["python", "-m", "atlas_init", *command_args, *extra_sys_args]
    )
    assert actual_command == expected_command
    assert actual_args == expected_args


def test_default_settings(monkeypatch):
    monkeypatch.setenv(as_env_var_name("test_suites"), "suite1,suite2 suite3")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={settings.repo_path_rel_path}")
    assert settings.test_suites_parsed == ["suite1", "suite2", "suite3"]


def test_dumping_default_settings(monkeypatch, tmp_path):
    out_file = tmp_path / ".env"
    AtlasInitSettings.safe_settings()
    dump_manual_dotenv_from_env(out_file)
    loaded = dotenv.dotenv_values(out_file)
    assert sorted(loaded.keys()) == [
        "ATLAS_INIT_PROJECT_NAME",
        "AWS_PROFILE",
        "MONGODB_ATLAS_BASE_URL",
        "MONGODB_ATLAS_ORG_ID",
        "MONGODB_ATLAS_PRIVATE_KEY",
        "MONGODB_ATLAS_PUBLIC_KEY",
        "TF_CLI_CONFIG_FILE",
    ]
