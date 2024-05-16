from __future__ import annotations

import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple

from model_lib import field_names, parse_payload
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_init.cloud.aws import AwsRegion
from atlas_init.settings.config import (
    AtlasInitConfig,
    TestSuite,
)
from atlas_init.settings.config import (
    active_suites as config_active_suites,
)
from atlas_init.settings.path import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_PROFILES_PATH,
    DEFAULT_SCHEMA_CONFIG_PATH,
    DEFAULT_TF_PATH,
    load_dotenv,
    repo_path_rel_path,
)

logger = logging.getLogger(__name__)
ENV_PREFIX = "ATLAS_INIT_"
DEFAULT_PROFILE = "default"
REQUIRED_FIELDS = [
    "MONGODB_ATLAS_ORG_ID",
    "MONGODB_ATLAS_PRIVATE_KEY",
    "MONGODB_ATLAS_PUBLIC_KEY",
]


class ExternalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str = ""
    AWS_REGION: AwsRegion = "us-east-1"
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str
    MONGODB_ATLAS_BASE_URL: str = "https://cloud-dev.mongodb.com/"
    non_interactive: bool = False

    @property
    def is_interactive(self) -> bool:
        return not self.non_interactive


def as_env_var_name(field_name: str) -> str:
    names = set(field_names(AtlasInitSettings))
    assert (
        field_name in names or field_name.lower() in names
    ), f"unknown field name for {AtlasInitSettings}: {field_name}"
    external_settings_names = set(field_names(ExternalSettings))
    if field_name in external_settings_names:
        return field_name.upper()
    return f"{ENV_PREFIX}{field_name}".upper()


def dump_manual_dotenv_from_env(path: Path) -> None:
    env_vars: dict[str, str] = {}
    names = field_names(AtlasInitSettings)
    ext_settings_names = field_names(ExternalSettings)
    path_settings_names = field_names(AtlasInitPaths)
    names = set(names + ext_settings_names + path_settings_names)
    os_env = os.environ
    for name in sorted(names):
        env_name = as_env_var_name(name)
        if env_name.lower() in os_env or env_name.upper() in os_env:
            env_value = os_env.get(env_name.upper()) or os_env.get(env_name.lower())
            if env_value:
                env_vars[env_name] = env_value

    content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def env_var_names(field_name: str) -> list[str]:
    return [f"{ENV_PREFIX}{name}" for name in (field_name, field_name.lower(), field_name.upper())]


def read_from_env(field_name: str, default: str = "") -> str:
    assert as_env_var_name(field_name)
    for name in [field_name, field_name.lower(), field_name.upper()]:
        if name in os.environ:
            return os.environ[name]
        prefix_name = f"{ENV_PREFIX}{name}"
        if prefix_name in os.environ:
            return os.environ[prefix_name]
    logger.info(f"field not found in env: {field_name}, using default: {default}")
    return default


class AtlasInitPaths(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    profile: str = DEFAULT_PROFILE
    config_path: Path = DEFAULT_CONFIG_PATH
    tf_path: Path = DEFAULT_TF_PATH
    profiles_path: Path = DEFAULT_PROFILES_PATH
    tf_schema_config_path: Path = DEFAULT_SCHEMA_CONFIG_PATH
    schema_out_path: Path | None = None

    @property
    def schema_out_path_computed(self) -> Path:
        return self.schema_out_path or self.profile_dir / "schema"

    @property
    def profile_dir(self) -> Path:
        return self.profiles_path / self.profile

    @property
    def env_file_manual(self) -> Path:
        return self.profile_dir / ".env-manual"

    @property
    def manual_env_vars(self) -> dict[str, str]:
        env_manual_path = self.env_file_manual
        if env_manual_path.exists():
            return load_dotenv(env_manual_path)
        return {}

    @property
    def env_vars_generated(self) -> Path:
        return self.profile_dir / ".env-generated"

    @property
    def env_vars_vs_code(self) -> Path:
        return self.profile_dir / ".env-vscode"

    @property
    def tf_data_dir(self) -> Path:
        return self.profile_dir / ".terraform"

    @property
    def tf_vars_path(self) -> Path:
        return self.tf_data_dir / "vars.auto.tfvars.json"

    @property
    def tf_state_path(self) -> Path:
        return self.profile_dir / "tf_state"

    @property
    def tf_outputs_path(self) -> Path:
        return self.profile_dir / "tf_outputs.json"

    def load_env_vars(self, path: Path) -> dict[str, str]:
        return load_dotenv(path)

    def load_env_vars_generated(self) -> dict[str, str]:
        env_path = self.env_vars_generated
        assert env_path.exists(), f"no env-vars exist {env_path} have you forgotten apply?"
        return load_dotenv(env_path)

    def load_profile_manual_env_vars(self) -> dict[str, str]:
        manual_env_vars = self.manual_env_vars
        if manual_env_vars:
            logger.warning(f"loading manual env-vars from {self.env_file_manual}")
            os.environ.update(manual_env_vars)
        else:
            logger.warning(f"no {self.env_file_manual}")
        return manual_env_vars


class EnvVarsCheck(NamedTuple):
    missing: list[str]
    ambiguous: list[str]


class AtlasInitSettings(AtlasInitPaths, ExternalSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    cfn_profile: str = ""
    cfn_region: str = ""
    project_name: str = ""

    skip_copy: bool = False
    test_suites: str = ""

    @classmethod
    def check_env_vars(
        cls,
        profile: str = DEFAULT_PROFILE,
        required_extra_fields: list[str] | None = None,
        explicit_env_vars: dict[str, str] | None = None,
    ) -> EnvVarsCheck:
        """side effect of loading env-vars and set profile"""
        os.environ[as_env_var_name("profile")] = profile
        required_extra_fields = required_extra_fields or []
        explicit_env_vars = explicit_env_vars or {}
        path_settings = AtlasInitPaths()
        manual_env_vars = path_settings.load_profile_manual_env_vars()
        ambiguous: list[str] = []
        for env_name, env_value in explicit_env_vars.items():
            manual_value = manual_env_vars.get(env_name)
            if manual_value and manual_value != env_value:
                ambiguous.append(env_name)
            else:
                os.environ[env_name] = env_value
        missing_env_vars = sorted(
            as_env_var_name(field_name)
            for field_name in REQUIRED_FIELDS + required_extra_fields
            if read_from_env(field_name) == ""
        )
        return EnvVarsCheck(missing=missing_env_vars, ambiguous=sorted(ambiguous))

    @classmethod
    def safe_settings(cls) -> AtlasInitSettings:
        """loads .env_manual before creating the settings"""
        path_settings = AtlasInitPaths()
        path_settings.load_profile_manual_env_vars()
        ext_settings = ExternalSettings()  # type: ignore
        path_settings = AtlasInitPaths()
        return cls(**path_settings.model_dump(), **ext_settings.model_dump())

    @field_validator("test_suites", mode="after")
    @classmethod
    def ensure_whitespace_replaced_with_commas(cls, value: str) -> str:
        return value.strip().replace(" ", ",")

    @model_validator(mode="after")
    def post_init(self):
        self.cfn_region = self.cfn_region or self.AWS_REGION
        return self

    @cached_property
    def config(self) -> AtlasInitConfig:
        config_path = Path(self.config_path) if self.config_path else DEFAULT_CONFIG_PATH
        assert config_path.exists(), f"no config path found @ {config_path}"
        yaml_parsed = parse_payload(config_path)
        assert isinstance(yaml_parsed, dict), f"config must be a dictionary, got {yaml_parsed}"
        return AtlasInitConfig(**yaml_parsed)

    @property
    def test_suites_parsed(self) -> list[str]:
        return [t for t in self.test_suites.split(",") if t]

    def cfn_config(self) -> dict[str, Any]:
        if self.cfn_profile:
            return {"cfn_config": {"profile": self.cfn_profile, "region": self.cfn_region}}
        return {}


def active_suites(settings: AtlasInitSettings) -> list[TestSuite]:
    repo_path, cwd_rel_path = repo_path_rel_path()
    return config_active_suites(settings.config, repo_path, cwd_rel_path, settings.test_suites_parsed)


def init_settings() -> AtlasInitSettings:
    return AtlasInitSettings.safe_settings()
