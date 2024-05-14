from dataclasses import dataclass, field

import dotenv
import pytest
from atlas_init.settings.env_vars import (
    REQUIRED_FIELDS,
    AtlasInitSettings,
    EnvVarsCheck,
    as_env_var_name,
    dump_manual_dotenv_from_env,
)
from atlas_init.settings.path import repo_path_rel_path

from test_atlas_init.conftest import mongodb_atlas_required_vars, write_required_vars


def test_set_profiles_path(tmp_paths, tmp_path):
    assert tmp_paths.profiles_path == tmp_path


@dataclass
class _TestCase:
    name: str
    env_vars_in_file: dict = field(default_factory=dict)
    required_extra: list[str] = field(default_factory=list)
    explicit_env_vars: dict = field(default_factory=dict)
    expected_missing: list[str] = field(default_factory=list)
    expected_ambiguous: list[str] = field(default_factory=list)

    @property
    def expected(self) -> EnvVarsCheck:
        return EnvVarsCheck(
            sorted(self.expected_missing),
            sorted(self.expected_ambiguous),
        )


ENV_VARS_CHECKS = [
    _TestCase(
        "empty env-vars, should list default required",
        expected_missing=REQUIRED_FIELDS,
    ),
    _TestCase(
        "empty env-vars + project_name, should list all",
        expected_missing=REQUIRED_FIELDS + ["ATLAS_INIT_PROJECT_NAME"],
        required_extra=["project_name"],
    ),
    _TestCase(
        "ok",
        env_vars_in_file=mongodb_atlas_required_vars(),
    ),
    _TestCase(
        "missing project_name",
        env_vars_in_file=mongodb_atlas_required_vars(),
        required_extra=["project_name"],
        expected_missing=["ATLAS_INIT_PROJECT_NAME"]
    ),
    _TestCase(
        "ok, project_name set",
        env_vars_in_file=mongodb_atlas_required_vars(),
        required_extra=["project_name"],
        explicit_env_vars={"ATLAS_INIT_PROJECT_NAME": "explicit"}
    ),
    _TestCase(
        "ambiguous project_name",
        env_vars_in_file={key: f"value_{key}" for key in REQUIRED_FIELDS}
        | {"ATLAS_INIT_PROJECT_NAME": "my-project"},
        explicit_env_vars={"ATLAS_INIT_PROJECT_NAME": "different-name"},
        expected_ambiguous=["ATLAS_INIT_PROJECT_NAME"],
    ),
]


@pytest.mark.parametrize(
    "test_case", ENV_VARS_CHECKS, ids=[test_case.name for test_case in ENV_VARS_CHECKS]
)
def test_check_env_vars(test_case, tmp_paths):
    if env_vars_in_file := test_case.env_vars_in_file:
        write_required_vars(tmp_paths, env_vars_in_file)
    assert (
        AtlasInitSettings.check_env_vars(
            required_extra_fields=test_case.required_extra,
            explicit_env_vars=test_case.explicit_env_vars,
        )
        == test_case.expected
    )


@pytest.mark.skip("needs a profile to exist")
def test_default_settings(monkeypatch):
    monkeypatch.setenv(as_env_var_name("test_suites"), "suite1,suite2 suite3")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={repo_path_rel_path()}")
    assert settings.test_suites_parsed == ["suite1", "suite2", "suite3"]


@pytest.mark.skip("needs a profile to exist")
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
