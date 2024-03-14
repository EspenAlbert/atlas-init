import os
import sys
from functools import cached_property
from pathlib import Path
from typing import Literal

import dotenv
from model_lib import parse_payload
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_init.config import AtlasInitConfig

REPO_PATH = Path(__file__).parent.parent.parent
CONFIG_PATH = REPO_PATH / "atlas_init.yaml"


def as_profile_dir(name: str) -> Path:
    return REPO_PATH / f"profiles/{name}"


def env_file_manual_profile(name: str) -> Path:
    return as_profile_dir(name) / ".env_manual"


class ExternalSettings(BaseSettings):
    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str = "mms-scratch"
    AWS_REGION: str = ""
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str


class AtlasInitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_INIT_")
    external_settings: ExternalSettings = Field(default_factory=ExternalSettings)
    
    profile: str = "default"
    command: Literal["init", "apply", "destroy"] = "init"
    unique_name: str = ""
    config_path: str = ""
    cfn_secret: bool = False
    branch_name: str = ""
    out_dir: str = ""

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

    @model_validator(mode="after")
    def set_command_from_sys_args(self):
        *_, last_arg = sys.argv
        if last_arg in {"init", "apply", "destroy"}:
            self.ATLAS_INIT_COMMAND = last_arg
        assert self.repo_path_rel_path
        return self

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
        config_path = (
            Path(self.config_path) if self.config_path else CONFIG_PATH
        )
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
    def tf_vars_path(self) -> Path:
        return self.profile_dir / "terraform/vars.auto.tfvars.json"

if __name__ == "__main__":
    print(f"repo_path={REPO_PATH}")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={settings.repo_path_rel_path}")
