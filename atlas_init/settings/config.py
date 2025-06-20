from __future__ import annotations

import fnmatch
import logging
from collections import defaultdict
from collections.abc import Iterable
from functools import total_ordering
from os import getenv
from pathlib import Path
from typing import Any

from model_lib import Entity, IgnoreFalsy
from pydantic import Field, model_validator

from atlas_init.repos.path import as_repo_alias, find_test_names, go_package_prefix, owner_project_name, package_glob

logger = logging.getLogger(__name__)


class TerraformVars(IgnoreFalsy):
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
    use_encryption_at_rest: bool = False

    def __add__(self, other: TerraformVars):  # type: ignore
        assert isinstance(other, TerraformVars)  # type: ignore
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
        if self.use_encryption_at_rest:
            config["use_encryption_at_rest"] = True
        if self.stream_instance:
            # hack until backend bug with stream instance is fixed
            config["stream_instance_config"] = {"name": getenv("ATLAS_STREAM_INSTANCE_NAME", "atlas-init")}
        return config


class PyHook(Entity):
    name: str
    locate: str


@total_ordering
class TestSuite(IgnoreFalsy):
    __test__ = False

    name: str
    sequential_tests: bool = False
    repo_go_packages: dict[str, list[str]] = Field(default_factory=dict)
    vars: TerraformVars = Field(default_factory=TerraformVars)  # type: ignore
    post_apply_hooks: list[PyHook] = Field(default_factory=list)

    def __lt__(self, other) -> bool:
        if not isinstance(other, TestSuite):  # type: ignore
            raise TypeError
        return self.name < other.name

    def package_url_tests(self, repo_path: Path, prefix: str = "") -> dict[str, dict[str, Path]]:
        alias = as_repo_alias(repo_path)
        packages = self.repo_go_packages.get(alias, [])
        names = defaultdict(dict)
        for package in packages:
            pkg_name = f"{go_package_prefix(repo_path)}/{package}"
            for go_file in repo_path.glob(f"{package}/*.go"):
                for name in find_test_names(go_file, prefix):
                    names[pkg_name][name] = go_file.parent
        return names

    def is_active(self, repo_alias: str, change_paths: Iterable[str]) -> bool:
        """changes paths should be relative to the repo"""
        globs = [package_glob(pkg) for pkg in self.repo_go_packages.get(repo_alias, [])]
        return any(any(fnmatch.fnmatch(path, glob) for glob in globs) for path in change_paths)

    def cwd_is_repo_go_pkg(self, cwd: Path, repo_alias: str) -> bool:
        alias_packages = self.repo_go_packages[repo_alias]
        for pkg_path in alias_packages:
            if str(cwd).endswith(pkg_path):
                return True
        logger.warning(f"no go package found for repo {repo_alias} in {cwd}")
        return False


class RepoAliasNotFoundError(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


class AtlasInitConfig(Entity):
    repo_aliases: dict[str, str] = Field(default_factory=dict)
    test_suites: list[TestSuite] = Field(default_factory=list)  # type: ignore

    def repo_alias(self, repo_url_path: str) -> str:
        alias = self.repo_aliases.get(repo_url_path)
        if alias is None:
            raise RepoAliasNotFoundError(repo_url_path)
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
    ) -> list[TestSuite]:  # type: ignore
        forced_suites = set(forced_test_suites)
        if forced_test_suites:
            logger.warning(f"using forced test suites: {forced_test_suites}")
        return [
            suit
            for suit in self.test_suites
            if suit.name in forced_suites or (alias and suit.is_active(alias, change_paths))
        ]

    @model_validator(mode="after")
    def ensure_all_repo_aliases_are_found(self):
        missing_aliases = set()
        aliases = set(self.repo_aliases.values())
        for group in self.test_suites:
            if more_missing := (group.repo_go_packages.keys() - aliases):
                logger.warning(f"repo aliases not found for group={group.name}: {more_missing}")
                missing_aliases |= more_missing
        if missing_aliases:
            raise ValueError(f"repo aliases not found: {missing_aliases}")
        return self


def active_suites(
    config: AtlasInitConfig,
    repo_path: Path,
    cwd_rel_path: str,
    forced_test_suites: list[str],
) -> list[TestSuite]:  # type: ignore
    repo_url_path = owner_project_name(repo_path)
    try:
        repo_alias = config.repo_alias(repo_url_path)
    except RepoAliasNotFoundError:
        if forced_test_suites:
            # still want to use the forced test suites
            repo_alias = None
        else:
            raise
    logger.info(
        f"repo_alias={repo_alias}, repo_path={repo_path}, repo_url_path={repo_url_path}, cwd_rel_path={cwd_rel_path}"
    )
    change_paths = [cwd_rel_path]
    active_suites = config.active_test_suites(repo_alias, change_paths, forced_test_suites)
    logger.info(f"active_suites: {[s.name for s in active_suites]}")
    return active_suites
