from dataclasses import dataclass, field

import pytest

from atlas_init.settings.env_vars import (
    ENV_PROJECT_NAME,
    ENV_TEST_SUITES,
    PLACEHOLDER_VALUE,
    REQUIRED_FIELDS,
    AtlasInitSettings,
    EnvVarsCheck,
    init_settings,
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
    expected_missing: list[str] = field(default_factory=list)
    expected_ambiguous: list[str] = field(default_factory=list)
    explicit_env_vars: dict = field(default_factory=dict)

    @property
    def expected(self) -> EnvVarsCheck:
        return EnvVarsCheck(
            sorted(self.expected_missing),
            sorted(self.expected_ambiguous),
        )

    def load_env_vars(self, monkeypatch):
        for key, value in self.explicit_env_vars.items():
            monkeypatch.setenv(key, value)


ENV_VARS_CHECKS = [
    _TestCase(
        "empty env-vars, should list default required",
        expected_missing=REQUIRED_FIELDS,
    ),
    _TestCase(
        "empty env-vars + project_name, should list all",
        expected_missing=REQUIRED_FIELDS + [ENV_PROJECT_NAME],
        required_extra=[ENV_PROJECT_NAME],
    ),
    _TestCase(
        "ok",
        env_vars_in_file=mongodb_atlas_required_vars(),
    ),
    _TestCase(
        "missing project_name",
        env_vars_in_file=mongodb_atlas_required_vars(),
        required_extra=[ENV_PROJECT_NAME],
        expected_missing=[ENV_PROJECT_NAME],
    ),
    _TestCase(
        "ok, project_name set",
        env_vars_in_file=mongodb_atlas_required_vars() | {ENV_PROJECT_NAME: "explicit"},
        required_extra=[ENV_PROJECT_NAME],
    ),
    _TestCase(
        "ambiguous project_name",
        env_vars_in_file={key: f"value_{key}" for key in REQUIRED_FIELDS}
        | {ENV_PROJECT_NAME: "my-project"},
        explicit_env_vars={ENV_PROJECT_NAME: "different-name"},
        expected_ambiguous=[ENV_PROJECT_NAME],
    ),
]


@pytest.mark.parametrize(
    "test_case", ENV_VARS_CHECKS, ids=[test_case.name for test_case in ENV_VARS_CHECKS]
)
def test_check_env_vars(monkeypatch, test_case, tmp_paths):
    if env_vars_in_file := test_case.env_vars_in_file:
        write_required_vars(tmp_paths, env_vars_in_file)
    test_case.load_env_vars(monkeypatch)
    assert (
        AtlasInitSettings.check_env_vars(
            required_env_vars=test_case.required_extra,
        )
        == test_case.expected
    )


def test_init_settings_non_required_use_placeholders(tmp_paths):
    settings = init_settings(non_required=True)
    settings_dict = settings.model_dump()
    placehodler_values = [settings_dict.get(key, "") for key in REQUIRED_FIELDS]
    assert placehodler_values == [PLACEHOLDER_VALUE] * len(REQUIRED_FIELDS)


@pytest.mark.skip("needs a profile to exist")
def test_default_settings(monkeypatch):
    monkeypatch.setenv(ENV_TEST_SUITES, "suite1,suite2 suite3")
    settings = init_settings()
    print(settings)
    print(f"repo_path,rel_path={repo_path_rel_path()}")
    assert settings.test_suites_parsed == ["suite1", "suite2", "suite3"]
