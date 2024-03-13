import fnmatch
import os
import logging
from pathlib import Path
from typing import Iterable
from model_lib import Entity
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)

class TerraformVars(Entity):
    cluster_info: bool = False
    stream_instance: bool = False

class ChangeGroup(Entity):
    name: str
    sequential_tests: bool = False
    go_packages: list[str] = Field(default_factory=list)
    repo_globs: dict[str, list[str]] = Field(default_factory=dict)
    vars: TerraformVars = Field(default_factory=TerraformVars)

    def all_globs(self, repo_alias: str) -> list[str]:
        return self.repo_globs.get(repo_alias, []) + [
            f"{pkg}/*.go" for pkg in self.go_packages
        ]

    def is_active(self, repo_alias: str, changes_paths: Iterable[str]) -> bool:
        """changes paths should be relative to the repo"""
        globs = self.all_globs(repo_alias)
        for path in changes_paths:
            if any(fnmatch.fnmatch(path, glob) for glob in globs):
                return True
        return False


class AtlasInitConfig(Entity):
    use_dev_cloud: bool = False
    change_groups: list[ChangeGroup] = Field(default_factory=list)
    repo_aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_all_repo_aliases_are_found(self):
        missing_aliases = set()
        aliases = set(self.repo_aliases.keys())
        for group in self.change_groups:
            if more_missing := group.repo_globs.keys() - aliases:
                logger.warning(f"repo aliases not found for group={group.name}: {more_missing}")
                missing_aliases |= more_missing
        if missing_aliases:
            raise ValueError(f"repo aliases not found: {missing_aliases}")
        return self
