from __future__ import annotations

import logging
import os
import sys
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, cast

import dotenv
from model_lib import field_names, parse_payload
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.prompt import Prompt
from zero_3rdparty.enum_utils import StrEnum

from atlas_init.config import AtlasInitConfig

logger = logging.getLogger(__name__)
REPO_PATH = Path(__file__).parent.parent.parent
CONFIG_PATH = REPO_PATH / "atlas_init.yaml"


def as_profile_dir(name: str) -> Path:
    return REPO_PATH / f"profiles/{name}"


def env_file_manual_profile(name: str) -> Path:
    return as_profile_dir(name) / ".env_manual"


class AtlasInitCommand(StrEnum):
    INIT = "init"
    APPLY = "apply"
    DESTROY = "destroy"
    TEST_GO = "test_go"
    CONFIG = "config"

    @classmethod
    def is_terraform_command(cls, value: AtlasInitCommand) -> bool:
        return value in {cls.INIT, cls.APPLY, cls.DESTROY}


SUPPORTED_CLI_COMMANDS = list(AtlasInitCommand)


def validate_command_and_args(
    command: AtlasInitCommand | None, sys_args: list[str]
) -> tuple[AtlasInitCommand, list[str]]:
    try:
        module_index = next(i for i, arg in enumerate(sys_args) if "atlas_init" in arg)
    except StopIteration:
        if "pytest" in sys_args[0]:
            module_index = len(sys_args)
        else:
            raise ValueError(f"unable to find atlas_init in the sys_args! {sys_args}")
    command_index = module_index + 1
    if command_index < len(sys_args):
        command_cli, *command_args = sys_args[command_index:]
        if command_cli not in SUPPORTED_CLI_COMMANDS:
            raise ValueError(
                f"unknown command: {command_cli}, expected on of {SUPPORTED_CLI_COMMANDS}"
            )
        command = cast(AtlasInitCommand, command_cli)
    else:
        command_args = []
    if command is None:
        command = AtlasInitCommand.INIT
        logger.warning(f"using default command: {command}")
    return command, command_args


class ExternalSettings(BaseSettings):
    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str = "mms-scratch"
    AWS_REGION: str = "us-east-1"
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str


def as_env_var_name(field_name: str) -> str:
    names = set(field_names(AtlasInitSettings))
    assert (
        field_name in names
    ), f"unknown field name for {AtlasInitSettings}: {field_name}"
    return f"{AtlasInitSettings.ENV_PREFIX}{field_name}".upper()


class AtlasInitSettings(BaseSettings):
    ENV_PREFIX: ClassVar[str] = "ATLAS_INIT_"
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    external_settings: ExternalSettings = Field(default_factory=ExternalSettings)  # type: ignore

    profile: str = "default"
    command: AtlasInitCommand = AtlasInitCommand.INIT
    cfn_profile: str = ""
    cfn_region: str = ""
    project_name: str = ""
    config_path: str = ""
    out_dir: str = ""
    skip_copy: bool = False
    test_suites: str = ""

    branch_name: str = ""
    command_args: list[str] = Field(default_factory=list)

    @classmethod
    def safe_settings(cls, **kwargs):
        """loads .env_manual before creating the settings"""
        profile_name = os.getenv(
            "ATLAS_INIT_PROFILE", os.getenv("atlas_init_profile", "default")
        )
        env_file_manual = env_file_manual_profile(profile_name)
        if env_file_manual.exists():
            dotenv.load_dotenv(env_file_manual)
        return cls()

    @field_validator("test_suites", mode="after")
    def ensure_whitespace_replaced_with_commas(value: str) -> str:
        return value.strip().replace(" ", ",")

    @model_validator(mode="after")
    def post_init(self):
        self.command, self.command_args = validate_command_and_args(
            self.command, sys.argv
        )
        assert self.repo_path_rel_path  # type: ignore
        self.out_dir = self.out_dir or str(self.profile_dir)
        self.cfn_region = self.cfn_region or self.external_settings.AWS_REGION
        return self

    @property
    def is_terraform_command(self) -> bool:
        return AtlasInitCommand.is_terraform_command(self.command)

    @cached_property
    def repo_path_rel_path(self) -> tuple[Path, str]:
        cwd = Path(os.path.curdir).absolute()
        rel_path = []
        for path in [cwd, *cwd.parents]:
            if (path / ".git").exists():
                return path, "/".join(reversed(rel_path))
            rel_path.append(path.name)
        raise ValueError("no repo path found from cwd")

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
            return {k: v for k, v in dotenv.dotenv_values(env_manual_path).items() if v}
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
    def test_suites_parsed(self) -> list[str]:
        return [t for t in self.test_suites.split(",") if t]

    def cfn_config(self) -> dict[str, Any]:
        if self.cfn_profile:
            return dict(
                cfn_config={"profile": self.cfn_profile, "region": self.cfn_region}
            )
        return {}


_defaults = dict(
    TF_CLI_CONFIG_FILE = "",
    AWS_PROFILE = "mms-scratch",
    AWS_REGION = "us-east-1",
    MONGODB_ATLAS_ORG_ID="",
    MONGODB_ATLAS_PRIVATE_KEY="",
    MONGODB_ATLAS_PUBLIC_KEY="",
)
_dev_tfrc = """\
This points to your terraform `dev.tfrc` file,
usually, it will look something like this

provider_installation {
 
  dev_overrides {
 
    "mongodb/mongodbatlas" = "REPO_PATH_TF_PROVIDER/bin"
 
  }
 
  direct {}
 
}
"""
def example_tf_cli_config_file(repo_path_tf_provider: Path) -> str:
    return _dev_tfrc.replace("REPO_PATH_TF_PROVIDER", str(repo_path_tf_provider))


_help_existing = dict(
    TF_CLI_CONFIG_FILE="CLI_EXAMPLE",
    AWS_PROFILE="",
    AWS_REGION="",
    MONGODB_ATLAS_ORG_ID="",
    MONGODB_ATLAS_PRIVATE_KEY="",
    MONGODB_ATLAS_PUBLIC_KEY="",
)

_all_keys = set(_help_existing.keys())


def populate_help(repo_path_tf_provider: Path) -> dict[str, str]:
    return {**_help_existing} | {"TF_CLI_CONFIG_FILE": example_tf_cli_config_file(repo_path_tf_provider)}

def create_env_vars():
    profile = Prompt.ask(
        "What profile would you like to configure? (use empty for 'default')"
    ) or "default"
    logger.info(f"about to create a new profile={profile} ctrl+c to abort")
    env_file_path = env_file_manual_profile(profile)
    logger.info(f"will populate file: '{env_file_path}'")
    existing_variables: dict[str, str] = {}
    if env_file_path.exists():
        existing_variables = {k:v for k,v in dotenv.dotenv_values(env_file_path).items() if v}
    remaining_variables = _all_keys - existing_variables.keys()
    while remaining_variables:
        new_key, new_value = prompt_next_key_value(existing_variables)


def prompt_next_key_value(existing_variables: dict[str, str]) -> tuple[str, str]:
    # continue from here
    raise NotImplementedError
    

