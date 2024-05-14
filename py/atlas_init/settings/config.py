from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, Iterable

from model_lib import Entity
from pydantic import Field, model_validator

from atlas_init.repos.path import owner_project_name

logger = logging.getLogger(__name__)


class TerraformVars(Entity):
    cluster_info: bool = False
    cluster_info_m10: bool = False
    stream_instance: bool = False
    use_private_link: bool = False
    use_vpc_peering: bool = False
    use_project_extra: bool = False
    use_aws_vars: bool = False
    use_aws_vpc: bool = False
    use_aws_s3: bool = False
    use_federated_vars: bool = False

    def __add__(self, other: TerraformVars):
        assert isinstance(other, TerraformVars)
        kwargs = {k: v or getattr(other, k) for k, v in self}
        return type(self)(**kwargs)

    def as_configs(self) -> dict[str, Any]:
        config = {}
        if self.cluster_info or self.cluster_info_m10:
            instance_size = "M10" if self.cluster_info_m10 else "M0"
            cloud_backup = self.cluster_info_m10
            config["cluster_config"] = {
                "name": "atlas-init",
                "instance_size": instance_size,
                "database_in_url": "default",
                "cloud_backup": cloud_backup,
            }
        if self.use_private_link:
            config["use_private_link"] = True
        if self.use_vpc_peering:
            config["use_vpc_peering"] = True
        if self.use_aws_vars:
            config["use_aws_vars"] = True
        if self.use_aws_vpc:
            config["use_aws_vpc"] = True
        if self.use_aws_s3:
            config["use_aws_s3"] = True
        if self.use_project_extra:
            config["use_project_extra"] = True
        if self.use_federated_vars:
            config["use_federated_vars"] = True
        if self.stream_instance:
            config["stream_instance_config"] = {"name": "atlas-init"}
        return config


class TestSuite(Entity):
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

    def cwd_is_repo_go_pkg(self, cwd: Path, repo_alias: str) -> bool:
        alias_packages = self.repo_go_packages[repo_alias]
        for pkg_path in alias_packages:
            if str(cwd).endswith(pkg_path):
                return True
        logger.warning(f"no go package found for repo {repo_alias} in {cwd}")
        return False


class RepoAliasNotFound(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


class AtlasInitConfig(Entity):
    test_suites: list[TestSuite] = Field(default_factory=list)
    repo_aliases: dict[str, str] = Field(default_factory=dict)

    def repo_alias(self, repo_url_path: str) -> str:
        alias = self.repo_aliases.get(repo_url_path)
        if alias is None:
            raise RepoAliasNotFound(repo_url_path)
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
    ) -> list[TestSuite]:
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


def active_suites(
    config: AtlasInitConfig,
    repo_path: Path,
    cwd_rel_path: str,
    forced_test_suites: list[str],
) -> list[TestSuite]:
    repo_url_path = owner_project_name(repo_path)
    repo_alias = config.repo_alias(repo_url_path)
    logger.info(
        f"repo_alias={repo_alias}, repo_path={repo_path}, repo_url_path={repo_url_path}"
    )
    change_paths = [cwd_rel_path]

    active_suites = config.active_test_suites(
        repo_alias, change_paths, forced_test_suites
    )
    logger.info(f"active_suites: {[s.name for s in active_suites]}")
    return active_suites