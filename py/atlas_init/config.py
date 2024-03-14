from __future__ import annotations
import fnmatch
import logging
from typing import Iterable

from model_lib import Entity
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)


class TerraformVars(Entity):
    cluster_info: bool = False
    stream_instance: bool = False
    use_private_link: bool = False
    use_cluster: bool = False

    def __add__(self, other: TerraformVars):
        assert isinstance(other, TerraformVars)
        return type(self)(
            cluster_info=self.cluster_info or other.cluster_info,
            stream_instance=self.stream_instance or other.stream_instance,
            use_private_link=self.use_private_link or other.use_private_link,
        )

class ChangeGroup(Entity):
    name: str
    sequential_tests: bool = False
    repo_go_packages: dict[str, list[str]] = Field(default_factory=dict)
    repo_globs: dict[str, list[str]] = Field(default_factory=dict)
    vars: TerraformVars = Field(default_factory=TerraformVars)

    def all_globs(self, repo_alias: str) -> list[str]:
        go_packages = self.repo_go_packages.get(repo_alias, [])
        return self.repo_globs.get(repo_alias, []) + [
            f"{pkg}/*.go" for pkg in go_packages
        ] + go_packages

    def is_active(self, repo_alias: str, change_paths: Iterable[str]) -> bool:
        """changes paths should be relative to the repo"""
        globs = self.all_globs(repo_alias)
        for path in change_paths:
            if any(fnmatch.fnmatch(path, glob) for glob in globs):
                return True
        return False


class AtlasInitConfig(Entity):
    change_groups: list[ChangeGroup] = Field(default_factory=list)
    repo_aliases: dict[str, str] = Field(default_factory=dict)

    def active_change_groups(
        self, repo_url_path: str, change_paths: Iterable[str]
    ) -> list[ChangeGroup]:
        alias = self.repo_aliases.get(repo_url_path)
        if alias is None:
            raise ValueError(f"couldn't find {repo_url_path} in the config.repo_aliases")
        return [
            group
            for group in self.change_groups
            if group.is_active(alias, change_paths)
        ]

    @model_validator(mode="after")
    def ensure_all_repo_aliases_are_found(self):
        missing_aliases = set()
        aliases = set(self.repo_aliases.keys())
        for group in self.change_groups:
            if more_missing := group.repo_globs.keys() - aliases:
                logger.warning(
                    f"repo aliases not found for group={group.name}: {more_missing}"
                )
                missing_aliases |= more_missing
        if missing_aliases:
            raise ValueError(f"repo aliases not found: {missing_aliases}")
        return self
