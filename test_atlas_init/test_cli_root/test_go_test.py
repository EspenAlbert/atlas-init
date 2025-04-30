from atlas_init.cli_helper.go import GoEnvVars, GoTestCaptureMode, resolve_env_vars
import pytest
from test_atlas_init.conftest import CLIArgs


@pytest.mark.parametrize(
    "capture_mode,capture_env_vars",
    [
        (GoTestCaptureMode.capture, {"HTTP_MOCKER_CAPTURE": "true"}),
        (GoTestCaptureMode.replay, {"HTTP_MOCKER_REPLAY": "true"}),
        (GoTestCaptureMode.replay_and_update, {"HTTP_MOCKER_REPLAY": "true", "HTTP_MOCKER_DATA_UPDATE": "true"}),
        (GoTestCaptureMode.no_capture, {}),
    ],
)
def test_resolve_env_vars(cli_configure, capture_mode, capture_env_vars):
    settings = cli_configure(CLIArgs())
    actual = resolve_env_vars(
        settings,
        GoEnvVars.manual,
        capture_mode=capture_mode,
        use_old_schema=False,
        skip_os=True,
    )
    expected = {
        "ATLAS_INIT_PROJECT_NAME": "test_resolve_env_vars",
        "MONGODB_ATLAS_BASE_URL": "value_MONGODB_ATLAS_BASE_URL",
        "MONGODB_ATLAS_PREVIEW_PROVIDER_V2_ADVANCED_CLUSTER": "true",
        "MONGODB_ATLAS_ORG_ID": "value_MONGODB_ATLAS_ORG_ID",
        "MONGODB_ATLAS_PRIVATE_KEY": "value_MONGODB_ATLAS_PRIVATE_KEY",
        "MONGODB_ATLAS_PUBLIC_KEY": "value_MONGODB_ATLAS_PUBLIC_KEY",
        "TF_ACC": "1",
        "TF_LOG": "DEBUG",
    } | capture_env_vars
    assert actual == expected


def test_dict_pref():
    new_dict = {"a": 1}
    new_dict |= {"a": 2}
    assert new_dict == {"a": 2}
