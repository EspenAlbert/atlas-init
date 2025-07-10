from __future__ import annotations

import logging
import os
from contextlib import suppress
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

from model_lib import StaticSettings, parse_payload
from pydantic import BaseModel, ValidationError, field_validator
from zero_3rdparty import iter_utils, str_utils

from atlas_init.settings.config import (
    AtlasInitConfig,
    TestSuite,
)
from atlas_init.settings.config import (
    active_suites as config_active_suites,
)
from atlas_init.settings.path import (
    DEFAULT_ATLAS_INIT_CONFIG_PATH,
    DEFAULT_ATLAS_INIT_SCHEMA_CONFIG_PATH,
    DEFAULT_TF_SRC_PATH,
    dump_dotenv,
    load_dotenv,
    repo_path_rel_path,
)

logger = logging.getLogger(__name__)
ENV_PREFIX = "ATLAS_INIT_"
DEFAULT_PROFILE = "default"
DEFAULT_PROJECT_NAME = "atlas-init"
ENV_S3_PROFILE_BUCKET = f"{ENV_PREFIX}S3_PROFILE_BUCKET"
ENV_PROJECT_NAME = f"{ENV_PREFIX}PROJECT_NAME"
ENV_PROFILE = f"{ENV_PREFIX}PROFILE"
ENV_TEST_SUITES = f"{ENV_PREFIX}TEST_SUITES"
ENV_CLIPBOARD_COPY = f"{ENV_PREFIX}CLIPBOARD_COPY"
FILENAME_ENV_MANUAL = ".env-manual"
T = TypeVar("T")


def read_from_env(env_key: str, default: str = "") -> str:
    return next(
        (os.environ[name] for name in [env_key, env_key.lower(), env_key.upper()] if name in os.environ),
        default,
    )


class AtlasInitSettings(StaticSettings):
    atlas_init_profile: str = DEFAULT_PROFILE  # override this for different env, e.g. dev, prod
    atlas_init_project_name: str = DEFAULT_PROJECT_NAME  # used in the atlas cloud
    atlas_init_config_path: Path = DEFAULT_ATLAS_INIT_CONFIG_PATH  # /atlas_init.yaml
    atlas_init_tf_src_path: Path = DEFAULT_TF_SRC_PATH  # /tf directory of repo
    atlas_init_tf_schema_config_path: Path = DEFAULT_ATLAS_INIT_SCHEMA_CONFIG_PATH  # /terraform.yaml
    atlas_init_schema_out_path: Path | None = None  # override this for the generated schema
    atlas_init_static_html_path: Path | None = None

    atlas_init_cfn_profile: str = ""
    atlas_init_cfn_region: str = ""
    atlas_init_cfn_use_kms_key: bool = False
    atlas_init_cliboard_copy: str = ""
    atlas_init_test_suites: str = ""
    atlas_init_s3_profile_bucket: str = ""

    non_interactive: bool = False

    mongo_database: str = "atlas_init"
    mongo_url: str = "mongodb://user:pass@localhost:27017?retryWrites=true&w=majority&authSource=admin"

    @property
    def is_interactive(self) -> bool:
        return not self.non_interactive

    @property
    def profiles_path(self) -> Path:
        return self.static_root / "profiles"

    @property
    def project_name(self) -> str:
        return self.atlas_init_project_name

    @property
    def profile(self) -> str:
        return self.atlas_init_profile

    @property
    def schema_out_path_computed(self) -> Path:
        return self.atlas_init_schema_out_path or self.static_root / "schema"

    @property
    def profile_dir(self) -> Path:
        return self.profiles_path / self.profile

    @property
    def env_file_manual(self) -> Path:
        return self.profile_dir / FILENAME_ENV_MANUAL

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

    @property
    def github_ci_run_logs(self) -> Path:
        return self.cache_root / "github_ci_run_logs"

    @property
    def github_ci_summary_dir(self) -> Path:
        return self.cache_root / "github_ci_summary"

    def github_ci_summary_path(self, summary_name: str) -> Path:
        return self.github_ci_summary_dir / str_utils.ensure_suffix(summary_name, ".md")

    def github_ci_summary_details_path(self, summary_name: str, test_name: str) -> Path:
        return self.github_ci_summary_path(summary_name).parent / self.github_ci_summary_details_rel_path(
            summary_name, test_name
        )

    def github_ci_summary_details_rel_path(self, summary_name: str, test_name: str) -> str:
        return f"{summary_name.removesuffix('.md')}_details/{test_name}.md"

    @property
    def go_test_logs_dir(self) -> Path:
        return self.cache_root / "go_test_logs"

    @property
    def atlas_atlas_api_transformed_yaml(self) -> Path:
        return self.cache_root / "atlas_api_transformed.yaml"

    def cfn_region(self, default: str) -> str:
        return self.atlas_init_cfn_region or default

    def include_extra_env_vars_in_vscode(self, extra_env_vars: dict[str, str]) -> None:
        extra_name = ", ".join(extra_env_vars.keys())
        original_env_vars = load_dotenv(self.env_vars_vs_code)
        new_env_vars = original_env_vars | extra_env_vars
        dump_dotenv(self.env_vars_vs_code, new_env_vars)
        logger.info(f"done {self.env_vars_vs_code} updated with {extra_name} env-vars ✅")

    @field_validator(ENV_TEST_SUITES.lower(), mode="after")
    @classmethod
    def ensure_whitespace_replaced_with_commas(cls, value: str) -> str:
        return value.strip().replace(" ", ",")

    @cached_property
    def config(self) -> AtlasInitConfig:
        config_path = (
            Path(self.atlas_init_config_path) if self.atlas_init_config_path else DEFAULT_ATLAS_INIT_CONFIG_PATH
        )
        assert config_path.exists(), f"no config path found @ {config_path}"
        yaml_parsed = parse_payload(config_path)
        assert isinstance(yaml_parsed, dict), f"config must be a dictionary, got {yaml_parsed}"
        return AtlasInitConfig(**yaml_parsed)

    @property
    def test_suites_parsed(self) -> list[str]:
        return [t for t in self.atlas_init_test_suites.split(",") if t]

    def tf_vars(self, default_aws_region: str) -> dict[str, Any]:
        variables = {}
        if self.atlas_init_cfn_profile:
            variables["cfn_config"] = {
                "profile": self.atlas_init_cfn_profile,
                "region": self.atlas_init_cfn_region or default_aws_region,
                "use_kms_key": self.atlas_init_cfn_use_kms_key,
            }
        if self.atlas_init_s3_profile_bucket:
            variables["use_aws_s3"] = True
        return variables


class EnvVarsCheck(NamedTuple):
    missing: list[str]
    ambiguous: list[str]

    @property
    def is_ok(self) -> bool:
        return not self.missing and not self.ambiguous


def active_suites(settings: AtlasInitSettings) -> list[TestSuite]:  # type: ignore
    repo_path, cwd_rel_path = repo_path_rel_path()
    return config_active_suites(settings.config, repo_path, cwd_rel_path, settings.test_suites_parsed)


class EnvVarsError(Exception):
    def __init__(self, missing: list[str], ambiguous: list[str]):
        self.missing = missing
        self.ambiguous = ambiguous
        super().__init__(f"missing: {missing}, ambiguous: {ambiguous}")

    def __str__(self) -> str:
        return f"missing: {self.missing}, ambiguous: {self.ambiguous}"


def collect_required_env_vars(settings_classes: list[type[BaseModel]]) -> list[str]:
    cls_required_env_vars: dict[str, list[str]] = {}
    for cls in settings_classes:
        try:
            cls()
        except ValidationError as error:
            cls_required_env_vars[cls.__name__] = [".".join(str(loc) for loc in e["loc"]) for e in error.errors()]
    return list(iter_utils.flat_map(cls_required_env_vars.values()))


def detect_ambiguous_env_vars(manual_env_vars: dict[str, str]) -> list[str]:
    ambiguous: list[str] = []
    for env_name, manual_value in manual_env_vars.items():
        env_value = read_from_env(env_name)
        if env_value and manual_value != env_value:
            ambiguous.append(env_name)
    return ambiguous


def find_missing_env_vars(required_env_vars: list[str], manual_env_vars: dict[str, str]) -> list[str]:
    return sorted(
        env_name for env_name in required_env_vars if read_from_env(env_name) == "" and env_name not in manual_env_vars
    )


def init_settings(
    *settings_classes: type[BaseModel],
    skip_ambiguous_check: bool = False,
) -> AtlasInitSettings:
    settings = AtlasInitSettings.from_env()
    profile_env_vars = settings.manual_env_vars
    vscode_env_vars = settings.env_vars_vs_code
    if vscode_env_vars.exists():
        profile_env_vars |= load_dotenv(vscode_env_vars)
    required_env_vars = collect_required_env_vars(list(settings_classes))
    ambiguous = [] if skip_ambiguous_check else detect_ambiguous_env_vars(profile_env_vars)
    missing_env_vars = find_missing_env_vars(required_env_vars, profile_env_vars)

    if ambiguous:
        logger.warning(
            f"ambiguous env_vars: {ambiguous} (specified both in cli/env & in .env-(manual|vscode) file with different values)"
        )
    if missing_env_vars or ambiguous:
        raise EnvVarsError(missing_env_vars, ambiguous)

    if new_updates := {k: v for k, v in profile_env_vars.items() if k not in os.environ}:
        logger.info(f"loading env-vars {','.join(sorted(new_updates))}")
        os.environ |= new_updates
    for cls in settings_classes:
        cls()  # ensure any errors are raised
    return AtlasInitSettings.from_env()


def env_vars_cls_or_none(t: type[T], *, dotenv_path: Path | None = None) -> T | None:
    explicit_vars: dict[str, str] = {}
    if dotenv_path and dotenv_path.exists():
        explicit_vars = load_dotenv(dotenv_path)
    with suppress(ValidationError):
        return t(**explicit_vars)
