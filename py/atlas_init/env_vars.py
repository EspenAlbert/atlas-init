import os
import sys
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

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
    AWS_REGION: str = "us-east-1"
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str


class AtlasInitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_INIT_")
    external_settings: ExternalSettings = Field(default_factory=ExternalSettings)

    profile: str = "default"
    command: Literal["init", "apply", "destroy"] = "init"
    cfn_profile: str = ""
    cfn_region: str = ""
    project_name: str = ""
    config_path: str = ""
    out_dir: str = ""
    skip_copy: bool = False

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
        return cls()

    @model_validator(mode="after")
    def post_init(self):
        *_, last_arg = sys.argv
        if last_arg in {"init", "apply", "destroy"}:
            self.command = last_arg # type: ignore
        assert self.repo_path_rel_path
        self.out_dir = self.out_dir or str(self.profile_dir)
        self.cfn_region = self.cfn_region or self.external_settings.AWS_REGION
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
    def tf_data_dir(self) -> Path:
        return self.profile_dir / ".terraform"
    
    @property
    def tf_vars_path(self) -> Path:
        return self.tf_data_dir / "vars.auto.tfvars.json"

    def cfn_config(self) -> dict[str, Any]:
        if self.cfn_profile:
            return dict(
                cfn_config={"profile": self.cfn_profile, "region": self.cfn_region}
            )
        return {}


if __name__ == "__main__":
    print(f"repo_path={REPO_PATH}")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={settings.repo_path_rel_path}")
