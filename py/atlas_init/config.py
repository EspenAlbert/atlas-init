from __future__ import annotations

import fnmatch
import logging
from typing import Any, Iterable

from model_lib import Entity
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)


class TerraformVars(Entity):
    cluster_info: bool = False
    stream_instance: bool = False
    use_private_link: bool = False

    def __add__(self, other: TerraformVars):
        assert isinstance(other, TerraformVars)
        return type(self)(
            cluster_info=self.cluster_info or other.cluster_info,
            stream_instance=self.stream_instance or other.stream_instance,
            use_private_link=self.use_private_link or other.use_private_link,
        )

    def as_configs(self) -> dict[str, Any]:
        config = {}
        if self.cluster_info:
            config["cluster_config"] = {
                "name": "atlas-init",
                "instance_size": "M0",
                "database_in_url": "default",
            }
        if self.use_private_link:
            config["use_private_link"] = True
        if self.stream_instance:
            config["stream_instance_config"] = {"name": "atlas-init"}
        return config


class TestSuit(Entity):
    name: str
    sequential_tests: bool = False
    repo_go_packages: dict[str, list[str]] = Field(default_factory=dict)
    repo_globs: dict[str, list[str]] = Field(default_factory=dict)
    vars: TerraformVars = Field(default_factory=TerraformVars)

    def all_globs(self, repo_alias: str) -> list[str]:
        go_packages = self.repo_go_packages.get(repo_alias, [])
        return (
            self.repo_globs.get(repo_alias, [])
            + [f"{pkg}/*.go" for pkg in go_packages]
            + go_packages
        )

    def is_active(self, repo_alias: str, change_paths: Iterable[str]) -> bool:
        """changes paths should be relative to the repo"""
        globs = self.all_globs(repo_alias)
        for path in change_paths:
            if any(fnmatch.fnmatch(path, glob) for glob in globs):
                return True
        return False


class AtlasInitConfig(Entity):
    test_suites: list[TestSuit] = Field(default_factory=list)
    repo_aliases: dict[str, str] = Field(default_factory=dict)

    def repo_alias(self, repo_url_path: str) -> str:
        alias = self.repo_aliases.get(repo_url_path)
        if alias is None:
            raise ValueError(
                f"couldn't find {repo_url_path} in the config.repo_aliases"
            )
        return alias

    def go_package_prefix(self, alias: str) -> str:
        for url_path, i_alias in self.repo_aliases.items():
            if alias == i_alias:
                return f"github.com/{url_path}"
        raise ValueError(f"alias not found: {alias}")

    def active_test_suites(
        self, alias: str, change_paths: Iterable[str], forced_test_suites: list[str]
    ) -> list[TestSuit]:
        forced_suites = set(forced_test_suites)
        return [
            suit
            for suit in self.test_suites
            if suit.is_active(alias, change_paths) or suit.name in forced_suites
        ]

    @model_validator(mode="after")
    def ensure_all_repo_aliases_are_found(self):
        missing_aliases = set()
        aliases = set(self.repo_aliases.keys())
        for group in self.test_suites:
            if more_missing := group.repo_globs.keys() - aliases:
                logger.warning(
                    f"repo aliases not found for group={group.name}: {more_missing}"
                )
                missing_aliases |= more_missing
        if missing_aliases:
            raise ValueError(f"repo aliases not found: {missing_aliases}")
        return self
