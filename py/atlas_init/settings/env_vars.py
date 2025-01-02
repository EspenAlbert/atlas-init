from __future__ import annotations

import logging
import os
from contextlib import suppress
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

import typer
from model_lib import parse_payload
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_init.cloud.aws import AwsRegion
from atlas_init.settings.config import (
    AtlasInitConfig,
    TestSuite,
)
from atlas_init.settings.config import (
    active_suites as config_active_suites,
)
from atlas_init.settings.env_vars_generated import AtlasSettings
from atlas_init.settings.path import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_PROFILES_PATH,
    DEFAULT_SCHEMA_CONFIG_PATH,
    DEFAULT_TF_PATH,
    dump_dotenv,
    load_dotenv,
    repo_path_rel_path,
)

logger = logging.getLogger(__name__)
ENV_PREFIX = "ATLAS_INIT_"
DEFAULT_PROFILE = "default"
ENV_S3_PROFILE_BUCKET = f"{ENV_PREFIX}S3_PROFILE_BUCKET"
ENV_PROJECT_NAME = f"{ENV_PREFIX}PROJECT_NAME"
ENV_PROFILE = f"{ENV_PREFIX}PROFILE"
ENV_PROFILES_PATH = f"{ENV_PREFIX}PROFILES_PATH"
ENV_TEST_SUITES = f"{ENV_PREFIX}TEST_SUITES"
ENV_CLIPBOARD_COPY = f"{ENV_PREFIX}CLIPBOARD_COPY"
REQUIRED_FIELDS = [
    "MONGODB_ATLAS_ORG_ID",
    "MONGODB_ATLAS_PRIVATE_KEY",
    "MONGODB_ATLAS_PUBLIC_KEY",
]
T = TypeVar("T")


class ExternalSettings(AtlasSettings):
    model_config = SettingsConfigDict(env_prefix="")

    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str = ""
    AWS_REGION: AwsRegion = "us-east-1"
    non_interactive: bool = False

    @property
    def realm_url(self) -> str:
        assert not self.is_mongodbgov_cloud, "realm_url is not supported for mongodbgov cloud"
        if "cloud-dev." in self.MONGODB_ATLAS_BASE_URL:
            return "https://services.cloud-dev.mongodb.com/"
        return "https://services.cloud.mongodb.com/"

    @property
    def is_interactive(self) -> bool:
        return not self.non_interactive

    @property
    def is_mongodbgov_cloud(self) -> bool:
        return "mongodbgov" in self.MONGODB_ATLAS_BASE_URL


def read_from_env(env_key: str, default: str = "") -> str:
    for name in [env_key, env_key.lower(), env_key.upper()]:
        if name in os.environ:
            return os.environ[name]
    return default


class AtlasInitPaths(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    profile: str = DEFAULT_PROFILE
    config_path: Path = DEFAULT_CONFIG_PATH
    tf_path: Path = DEFAULT_TF_PATH
    profiles_path: Path = DEFAULT_PROFILES_PATH
    tf_schema_config_path: Path = DEFAULT_SCHEMA_CONFIG_PATH
    schema_out_path: Path | None = None
    s3_profile_bucket: str = ""

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
        return load_dotenv(env_manual_path) if env_manual_path.exists() else {}

    @property
    def env_vars_generated(self) -> Path:
        return self.profile_dir / ".env-generated"

    @property
    def env_vars_vs_code(self) -> Path:
        return self.profile_dir / ".env-vscode"

    @property
    def env_vars_trigger(self) -> Path:
        return self.profile_dir / ".env-trigger"

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

    def load_env_vars_full(self) -> dict[str, str]:
        env_path = self.env_vars_vs_code
        assert env_path.exists(), f"no env-vars exist {env_path} have you forgotten apply?"
        return load_dotenv(env_path)

    def env_vars_cls_or_none(self, t: type[T], *, path: Path | None = None) -> T | None:
        with suppress(ValidationError):
            return self.env_vars_cls(t, path=path)

    def env_vars_cls(self, t: type[T], *, path: Path | None = None) -> T:
        path = path or self.env_vars_vs_code
        env_vars = self.load_env_vars(path) if path.exists() else {}
        return t(**env_vars)

    def load_profile_manual_env_vars(self, *, skip_os_update: bool = False) -> dict[str, str]:
        # sourcery skip: dict-assign-update-to-union
        manual_env_vars = self.manual_env_vars
        if manual_env_vars:
            if skip_os_update:
                return manual_env_vars
            if new_updates := {k: v for k, v in manual_env_vars.items() if k not in os.environ}:
                logger.info(f"loading manual env-vars {','.join(new_updates)}")
                os.environ.update(new_updates)
        else:
            logger.warning(f"no {self.env_file_manual}")
        return manual_env_vars

    def include_extra_env_vars_in_vscode(self, extra_env_vars: dict[str, str]) -> None:
        extra_name = ", ".join(extra_env_vars.keys())
        original_env_vars = self.load_env_vars(self.env_vars_vs_code)
        new_env_vars = original_env_vars | extra_env_vars
        dump_dotenv(self.env_vars_vs_code, new_env_vars)
        logger.info(f"done {self.env_vars_vs_code} updated with {extra_name} env-vars ✅")


class EnvVarsCheck(NamedTuple):
    missing: list[str]
    ambiguous: list[str]


class AtlasInitSettings(AtlasInitPaths, ExternalSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    cfn_profile: str = ""
    cfn_region: str = ""
    cfn_use_kms_key: bool = False
    project_name: str = ""

    cliboard_copy: str = ""
    test_suites: str = ""

    @classmethod
    def check_env_vars(
        cls,
        profile: str = DEFAULT_PROFILE,
        required_env_vars: list[str] | None = None,
    ) -> EnvVarsCheck:
        required_env_vars = required_env_vars or []
        path_settings = AtlasInitPaths(profile=profile)
        manual_env_vars = path_settings.manual_env_vars
        ambiguous: list[str] = []
        for env_name, manual_value in manual_env_vars.items():
            env_value = read_from_env(env_name)
            if env_value and manual_value != env_value:
                ambiguous.append(env_name)
        missing_env_vars = sorted(
            env_name
            for env_name in REQUIRED_FIELDS + required_env_vars
            if read_from_env(env_name) == "" and env_name not in manual_env_vars
        )
        return EnvVarsCheck(missing=missing_env_vars, ambiguous=sorted(ambiguous))

    @classmethod
    def safe_settings(cls, profile: str) -> AtlasInitSettings:
        """side effect of loading manual env-vars and set profile"""
        os.environ[ENV_PROFILE] = profile
        AtlasInitPaths(profile=profile).load_profile_manual_env_vars()
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

    def tf_vars(self) -> dict[str, Any]:
        variables = {}
        if self.cfn_profile:
            variables["cfn_config"] = {
                "profile": self.cfn_profile,
                "region": self.cfn_region,
                "use_kms_key": self.cfn_use_kms_key,
            }
        if self.s3_profile_bucket:
            variables["use_aws_s3"] = True
        return variables


def active_suites(settings: AtlasInitSettings) -> list[TestSuite]:
    repo_path, cwd_rel_path = repo_path_rel_path()
    return config_active_suites(settings.config, repo_path, cwd_rel_path, settings.test_suites_parsed)


_sentinel = object()


def init_settings(
    required_env_vars: list[str] | object = _sentinel,
) -> AtlasInitSettings:
    if required_env_vars is _sentinel:
        required_env_vars = [ENV_PROJECT_NAME]
    profile = os.getenv("ATLAS_INIT_PROFILE", DEFAULT_PROFILE)
    missing_env_vars, ambiguous_env_vars = AtlasInitSettings.check_env_vars(
        profile,
        required_env_vars=required_env_vars,  # type: ignore
    )
    if missing_env_vars:
        typer.echo(f"missing env_vars: {missing_env_vars}")
    if ambiguous_env_vars:
        typer.echo(
            f"amiguous env_vars: {ambiguous_env_vars} (specified both in cli & in .env-manual file with different values)"
        )
    if missing_env_vars or ambiguous_env_vars:
        raise typer.Exit(1)
    return AtlasInitSettings.safe_settings(profile)
