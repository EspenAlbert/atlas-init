from __future__ import annotations

import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

import dotenv
from model_lib import field_names, parse_payload
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_init.settings.config import (
    AtlasInitConfig,
    TestSuite,
)
from atlas_init.settings.config import (
    active_suites as config_active_suites,
)
from atlas_init.settings.path import (
    CONFIG_PATH,
    as_profile_dir,
    env_file_manual_profile,
    load_dotenv,
    repo_path_rel_path,
)

logger = logging.getLogger(__name__)


class ExternalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str
    AWS_REGION: str = "us-east-1"
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str
    MONGODB_ATLAS_BASE_URL: str = "https://cloud-dev.mongodb.com/"


def as_env_var_name(field_name: str) -> str:
    names = set(field_names(AtlasInitSettings))
    assert (
        field_name in names
    ), f"unknown field name for {AtlasInitSettings}: {field_name}"
    external_settings_names = set(field_names(ExternalSettings))
    if field_name in external_settings_names:
        return field_name.upper()
    return f"{AtlasInitSettings.ENV_PREFIX}{field_name}".upper()


def dump_manual_dotenv_from_env(path: Path) -> None:
    env_vars: dict[str, str] = {}
    names = field_names(AtlasInitSettings)
    ext_settings_names = field_names(ExternalSettings)
    names = set(names + ext_settings_names)
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


class AtlasInitSettings(ExternalSettings):
    ENV_PREFIX: ClassVar[str] = "ATLAS_INIT_"
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    profile: str = "default"
    cfn_profile: str = ""
    cfn_region: str = ""
    project_name: str
    # useful when pip-installing
    config_path: str = ""
    out_dir: str = ""
    skip_copy: bool = False
    test_suites: str = ""

    branch_name: str = ""

    @classmethod
    def safe_settings(cls, **kwargs):
        """loads .env_manual before creating the settings"""
        profile_name = os.getenv(
            "ATLAS_INIT_PROFILE", os.getenv("atlas_init_profile", "default")
        )
        env_file_manual = env_file_manual_profile(profile_name)
        if env_file_manual.exists():
            dotenv.load_dotenv(env_file_manual)
        else:
            try:
                ext_settings = ExternalSettings()  # type: ignore
                settings = cls(**ext_settings.model_dump())
            except ValidationError as e:
                logger.exception(e)
                logger.critical(
                    "missing env-vars for running atlas_init, see readme.md for help. Error Message above 👆 should also help"
                )
            else:
                logger.warning(
                    f"env_file @ {env_file_manual} did not exist, populating it"
                )
                dump_manual_dotenv_from_env(env_file_manual)
                return settings
        ext_settings = ExternalSettings()  # type: ignore
        return cls(**ext_settings.model_dump())

    @field_validator("test_suites", mode="after")
    def ensure_whitespace_replaced_with_commas(cls, value: str) -> str:
        return value.strip().replace(" ", ",")

    @model_validator(mode="after")
    def post_init(self):
        self.out_dir = self.out_dir or str(self.profile_dir)
        self.cfn_region = self.cfn_region or self.AWS_REGION
        return self

    @cached_property
    def config(self) -> AtlasInitConfig:
        config_path = Path(self.config_path) if self.config_path else CONFIG_PATH
        assert config_path.exists(), f"no config path found @ {config_path}"
        yaml_parsed = parse_payload(config_path)
        assert isinstance(
            yaml_parsed, dict
        ), f"config must be a dictionary, got {yaml_parsed}"
        return AtlasInitConfig(**yaml_parsed)

    @property
    def profile_dir(self) -> Path:
        return as_profile_dir(self.profile)

    @property
    def env_file_manual(self) -> Path:
        return env_file_manual_profile(self.profile)

    @property
    def manual_env_vars(self) -> dict[str, str]:
        env_manual_path = self.env_file_manual
        if env_manual_path.exists():
            return load_dotenv(env_manual_path)
        return {}

    @property
    def env_vars_generated(self) -> Path:
        return self.profile_dir / ".env-generated"

    def load_env_vars_generated(self) -> dict[str, str]:
        env_path = self.env_vars_generated
        assert (
            env_path.exists()
        ), f"no env-vars exist {env_path} have you forgotten apply?"
        return load_dotenv(env_path)

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
    def test_suites_parsed(self) -> list[str]:
        return [t for t in self.test_suites.split(",") if t]

    def cfn_config(self) -> dict[str, Any]:
        if self.cfn_profile:
            return dict(
                cfn_config={"profile": self.cfn_profile, "region": self.cfn_region}
            )
        return {}


def active_suites(settings: AtlasInitSettings) -> list[TestSuite]:
    repo_path, cwd_rel_path = repo_path_rel_path()
    return config_active_suites(
        settings.config, repo_path, cwd_rel_path, settings.test_suites_parsed
    )


def init_settings() -> AtlasInitSettings:
    return AtlasInitSettings.safe_settings()
