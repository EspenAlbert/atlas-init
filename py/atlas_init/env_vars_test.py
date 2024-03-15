import pytest

from atlas_init.env_vars import (
    AtlasInitCommand,
    AtlasInitSettings,
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


def test_default_settings():
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={settings.repo_path_rel_path}")
