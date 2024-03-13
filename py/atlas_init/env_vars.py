from functools import cached_property
import os
from pathlib import Path
import sys
from typing import Literal

import dotenv
from model_lib import parse_payload
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_init.config import AtlasInitConfig

REPO_PATH = Path(__file__).parent.parent.parent


def as_profile_dir(name: str) -> Path:
    return REPO_PATH / f"profiles/{name}"

def env_file_manual_profile(name: str) -> Path:
    return as_profile_dir(name) / ".env_manual"


class ExternalSettings(BaseSettings):
    TF_CLI_CONFIG_FILE: str = ""
    AWS_PROFILE: str = "mms-scratch"
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str

class AtlasInitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_INIT_")
    
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
        profile_name = os.getenv("ATLAS_INIT_PROFILE", os.getenv("atlas_init_profile", "default"))
        env_file_manual = env_file_manual_profile(profile_name)
        if env_file_manual.exists():
            dotenv.load_dotenv(env_file_manual)
        return cls()
    
    @model_validator(mode="after")
    def set_command_from_sys_args(self):
        *_, last_arg = sys.argv
        if last_arg in {"init", "apply", "destroy"}:
            self.ATLAS_INIT_COMMAND = last_arg
        assert self.repo_path
        return self

    @cached_property        
    def repo_path(self) -> Path:
        cwd = Path(os.path.curdir).absolute()
        for path in [cwd, *cwd.parents]:
            if (path / ".git").exists():
                return path
        raise ValueError("no repo path found from cwd")
    
    @cached_property
    def config(self) -> AtlasInitConfig:
        config_path = Path(self.config_path) if self.config_path else self.default_config_path
        assert config_path.exists(), f"no config path found @ {config_path}"
        yaml_parsed = parse_payload(config_path)
        assert isinstance(yaml_parsed, dict), f"config must be a dictionary, got {yaml_parsed}"
        return AtlasInitConfig(**yaml_parsed)

    @property
    def profile_dir(self) -> Path:
        return as_profile_dir(self.profile)
    
    @property
    def env_file_manual(self) -> Path:
        return env_file_manual_profile(self.profile)

    @property
    def default_config_path(self) -> Path:
        return self.profile_dir / "atlas_init.yaml"


if __name__ == "__main__":
    print(f"repo_path={REPO_PATH}")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path={settings.repo_path}")
