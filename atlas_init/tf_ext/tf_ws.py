from datetime import datetime
from enum import StrEnum
import fnmatch
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Self

import typer
import humanize
from ask_shell import run_and_wait, run_pool
from model_lib import Entity, dump, parse_model
from pydantic import ConfigDict, Field
from zero_3rdparty.file_utils import ensure_parents_write_text, iter_paths_and_relative
import stringcase

from atlas_init.cli_tf.hcl.modifier2 import TFVar
from atlas_init.settings.env_vars import init_settings
from atlas_init.settings.env_vars_generated import AtlasSettingsWithProject, AWSSettings
from atlas_init.tf_ext.paths import find_variables_typed
from atlas_init.tf_ext.settings import TfExtSettings, init_tf_ext_settings
from atlas_init.tf_ext.tf_mod_gen import validate_tf_workspace

logger = logging.getLogger(__name__)
LOCKFILE_NAME = ".terraform.tfstate.lock.info"
PascalAlias = ConfigDict(alias_generator=stringcase.pascalcase, populate_by_name=True)


class Lockfile(Entity):
    model_config = PascalAlias
    created: datetime
    path: str
    operation: str

    def __str__(self) -> str:
        return (
            f"lockfile for state {self.path} created={humanize.naturaltime(self.created)}, operation={self.operation})"
        )


class ResolvedEnvVar(Entity):
    var_matches: list[str] = Field(default_factory=list)
    name: str
    value: str
    sensitive: bool = False
    type: Literal["env"] = "env"

    def can_resolve(self, variable: TFVar) -> bool:
        return any(fnmatch.fnmatch(variable.name, var) for var in self.var_matches)


class ResolvedStringVar(Entity):
    var_matches: list[str] = Field(default_factory=list)
    value: str = ""
    sensitive: bool = False
    type: Literal["string"] = "string"

    def can_resolve(self, variable: TFVar) -> bool:
        if variable.type and variable.type != self.type:
            return False
        return any(fnmatch.fnmatch(variable.name, var) for var in self.var_matches)


ResolverVar = ResolvedStringVar | ResolvedEnvVar


def as_tfvars_env(resolver_vars: dict[str, ResolverVar]) -> tuple[dict[str, Any], dict[str, Any]]:
    env_vars = {}
    tf_vars = {}
    for var_name, var in resolver_vars.items():
        match var:
            case ResolvedEnvVar(name=name, value=value):
                env_vars[name] = value
            case ResolvedStringVar(value=value):
                tf_vars[var_name] = value
    return tf_vars, env_vars


class _MissingResolverVarsError(Exception):
    def __init__(self, missing_vars: list[str], path: Path, rel_path: str):
        self.missing_vars = missing_vars
        self.path = path
        self.rel_path = rel_path
        super().__init__(f"Missing variables: {missing_vars} for path: {path} with rel_path: {rel_path}")

    def __str__(self) -> str:
        return f"Missing variables: {self.missing_vars} for path: {self.path} with rel_path: {self.rel_path}"


class VariablesPlanResolver(Entity):
    paths: dict[str, list[ResolverVar]]

    def merge(self, other: Self) -> Self:
        merged = defaultdict(list)
        for path, vars in self.paths.items():
            merged[path].extend(vars)
        for path, vars in other.paths.items():
            merged[path].extend(vars)
        return type(self)(paths=merged)

    def variable_path_matches(self, path: Path, rel_path: str) -> list[ResolverVar]:
        resolved = []
        for path_pattern, vars in self.paths.items():
            if fnmatch.fnmatch(rel_path, path_pattern):
                resolved.extend(vars)
        return resolved

    def resolve_vars(self, path: Path, rel_path: str) -> dict[str, ResolverVar]:
        variables = find_variables_typed(path / "variables.tf")
        resolved_vars: dict[str, ResolverVar] = {}
        for var in variables.values():
            for resolver_var in self.variable_path_matches(path, rel_path):
                if resolver_var.can_resolve(var):
                    resolved_vars[var.name] = resolver_var
        if missing_vars := set(variables.keys()) - set(resolved_vars.keys()):
            raise _MissingResolverVarsError(sorted(missing_vars), path, rel_path)
        return resolved_vars


def update_dumped_vars(path: Path) -> VariablesPlanResolver:
    assert init_settings(AWSSettings, AtlasSettingsWithProject), "Settings must be initialized"
    project_settings = AtlasSettingsWithProject.from_env()
    dumped_vars = VariablesPlanResolver(
        paths={
            "*": [
                ResolvedStringVar(
                    var_matches=["project*"],
                    value=project_settings.MONGODB_ATLAS_PROJECT_ID,
                    sensitive=False,
                ),
                ResolvedStringVar(
                    var_matches=["org*"],
                    value=project_settings.MONGODB_ATLAS_ORG_ID,
                    sensitive=False,
                ),
                ResolvedEnvVar(
                    var_matches=["atlas_private_key"],
                    sensitive=True,
                    value=project_settings.MONGODB_ATLAS_PRIVATE_KEY,
                    name="MONGODB_ATLAS_PRIVATE_KEY",
                ),
                ResolvedEnvVar(
                    var_matches=["atlas_public_key"],
                    sensitive=True,
                    value=project_settings.MONGODB_ATLAS_PUBLIC_KEY,
                    name="MONGODB_ATLAS_PUBLIC_KEY",
                ),
                ResolvedEnvVar(
                    var_matches=["atlas_base_url"],
                    sensitive=False,
                    value=project_settings.MONGODB_ATLAS_BASE_URL,
                    name="MONGODB_ATLAS_BASE_URL",
                ),
            ]
        }
    )
    yaml = dump(dumped_vars, "yaml")
    ensure_parents_write_text(path, yaml)
    return dumped_vars


_ignored_workspace_dirs = [
    ".terraform",
]


class TFWorkspaceRunConfig(Entity):
    path: Path
    rel_path: str
    resolved_vars: dict[str, Any]
    resolved_env_vars: dict[str, Any]

    def tf_data_dir(self, settings: TfExtSettings) -> Path:
        repo_out = settings.repo_out
        assert self.path.is_relative_to(repo_out.base), f"path {self.path} is not relative to {repo_out.base}"
        relative_repo_path = str(self.path.relative_to(repo_out.base))
        return settings.static_root / "tf-ws-check" / relative_repo_path / ".terraform"

    def tf_vars_path_json(self, settings: TfExtSettings) -> Path:
        return self.tf_data_dir(settings) / "vars.auto.tfvars.json"


class TFWsCommands(StrEnum):
    VALIDATE = "validate"
    PLAN = "plan"
    APPLY = "apply"
    DESTROY = "destroy"


def tf_ws(
    command: TFWsCommands = typer.Argument("plan", help="The command to run in the workspace"),
    root_path: Path = typer.Option(
        ...,
        "-p",
        "--root-path",
        help="Path to the root directory, will recurse and look for **/main.tf",
        default_factory=Path.cwd,
    ),
):
    settings = init_tf_ext_settings()
    variable_resolvers = update_dumped_vars(settings.variable_plan_resolvers_dumped_file_path)
    manual_path = settings.variable_plan_resolvers_file_path
    if manual_path.exists():
        manual_resolvers = parse_model(manual_path, t=VariablesPlanResolver)
        variable_resolvers = variable_resolvers.merge(manual_resolvers)

    def include_path(rel_path: str) -> bool:
        return all(
            f"/{ignored_dir}/" not in rel_path and not rel_path.startswith(ignored_dir)
            for ignored_dir in _ignored_workspace_dirs
        )

    paths = sorted(
        (path.parent, rel_path)
        for path, rel_path in iter_paths_and_relative(root_path, "main.tf", only_files=True)
        if include_path(rel_path)
    )
    run_configs = []
    missing_vars_errors = []
    for path, rel_path in paths:
        try:
            resolver_vars = variable_resolvers.resolve_vars(path, rel_path)
            resolved_vars, resolved_env_vars = as_tfvars_env(resolver_vars)
            run_configs.append(
                TFWorkspaceRunConfig(
                    path=path, rel_path=rel_path, resolved_vars=resolved_vars, resolved_env_vars=resolved_env_vars
                )
            )
        except _MissingResolverVarsError as e:
            missing_vars_errors.append(e)
            continue
    if missing_vars_errors:
        missing_vars_formatted = "\n".join(str(e) for e in missing_vars_errors)
        logger.warning(f"Missing variables:\n{missing_vars_formatted}")

    run_count = len(run_configs)
    assert run_count > 0, f"No run configs found from {root_path}"

    def run_cmd(run_config: TFWorkspaceRunConfig):
        tf_vars_str = dump(run_config.resolved_vars, "pretty_json")
        tf_vars_path = run_config.tf_vars_path_json(settings)
        ensure_parents_write_text(tf_vars_path, tf_vars_str)
        env_extra = run_config.resolved_env_vars | {"TF_DATA_DIR": str(run_config.tf_data_dir(settings))}

        lockfile_path = run_config.path / LOCKFILE_NAME
        if lockfile_path.exists():
            lockfile = parse_model(lockfile_path, t=Lockfile, format="json")
            logger.warning(f"Lockfile exists for {run_config.path}, skipping: {lockfile}")
            return

        validate_tf_workspace(run_config.path, tf_cli_config_file=settings.tf_cli_config_file, env_extra=env_extra)
        if command == TFWsCommands.VALIDATE:
            return
        command_extra = ""
        if command in {TFWsCommands.APPLY, TFWsCommands.DESTROY}:
            command_extra = " -auto-approve"

        run_and_wait(
            f"terraform {command} -var-file={tf_vars_path}{command_extra}",
            cwd=run_config.path,
            env=env_extra,
            user_input=run_count == 1,
        )

    with run_pool(f"{command} in TF Workspaces", total=run_count, max_concurrent_submits=9) as pool:
        futures = {pool.submit(run_cmd, run_config): run_config for run_config in run_configs}
        for future, run_config in futures.items():
            try:
                future.result()
            except Exception as e:
                logger.error(f"Error running {command} for {run_config.path}: {e}")
                continue
