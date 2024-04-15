from __future__ import annotations

import fnmatch
import logging
from typing import Any, Iterable

from model_lib import Entity
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)


class TerraformVars(Entity):
    cluster_info: bool = False
    cluster_info_m10: bool = False
    stream_instance: bool = False
    use_private_link: bool = False
    use_vpc_peering: bool = False
    use_project_extra: bool = False

    def __add__(self, other: TerraformVars):
        assert isinstance(other, TerraformVars)
        kwargs = {k: v or getattr(other, k) for k, v in self}
        return type(self)(**kwargs)

    def as_configs(self) -> dict[str, Any]:
        config = {}
        if self.cluster_info or self.cluster_info_m10:
            instance_size = "M10" if self.cluster_info_m10 else "M0"
            config["cluster_config"] = {
                "name": "atlas-init",
                "instance_size": instance_size,
                "database_in_url": "default",
            }
        if self.use_private_link:
            config["use_private_link"] = True
        if self.use_vpc_peering:
            config["use_vpc_peering"] = True
        if self.use_project_extra:
            config["use_project_extra"] = True
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

class RepoAliastNotFound(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)

class AtlasInitConfig(Entity):
    test_suites: list[TestSuit] = Field(default_factory=list)
    repo_aliases: dict[str, str] = Field(default_factory=dict)

    def repo_alias(self, repo_url_path: str) -> str:
        alias = self.repo_aliases.get(repo_url_path)
        if alias is None:
            raise RepoAliastNotFound(repo_url_path)
        return alias

    def go_package_prefix(self, alias: str) -> str:
        for url_path, i_alias in self.repo_aliases.items():
            if alias == i_alias:
                return f"github.com/{url_path}"
        raise ValueError(f"alias not found: {alias}")

    def active_test_suites(
        self,
        alias: str | None,
        change_paths: Iterable[str],
        forced_test_suites: list[str],
    ) -> list[TestSuit]:
        forced_suites = set(forced_test_suites)
        if forced_test_suites:
            logger.warning(f"using forced test suites: {forced_test_suites}")
        return [
            suit
            for suit in self.test_suites
            if suit.name in forced_suites
            or (alias and suit.is_active(alias, change_paths))
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
