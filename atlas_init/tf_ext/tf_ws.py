from concurrent.futures import Future
from datetime import datetime
from enum import StrEnum
import fnmatch
import logging
from collections import defaultdict
import os
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
from atlas_init.repos.path import GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS, owner_project_name
from atlas_init.settings.env_vars import init_settings
from atlas_init.settings.env_vars_generated import AtlasSettingsWithProject, AWSSettings
from atlas_init.settings.path import load_dotenv, repo_path_rel_path
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


class ResolvedListVar(Entity):
    var_matches: list[str] = Field(default_factory=list)
    value: list = Field(default_factory=list)
    sensitive: bool = False
    type: Literal["list"] = "list"

    def can_resolve(self, variable: TFVar) -> bool:
        if variable.type and not variable.type.startswith("list"):
            return False
        return any(fnmatch.fnmatch(variable.name, var) for var in self.var_matches)


ResolverVar = ResolvedStringVar | ResolvedEnvVar | ResolvedListVar


def as_tfvars_env(resolver_vars: dict[str, ResolverVar]) -> tuple[dict[str, Any], dict[str, Any]]:
    env_vars = {}
    tf_vars = {}
    for var_name, var in resolver_vars.items():
        match var:
            case ResolvedEnvVar(name=name, value=value):
                env_vars[name] = value
            case ResolvedStringVar(value=value):
                tf_vars[var_name] = value
            case ResolvedListVar(value=value):
                tf_vars[var_name] = value
    return tf_vars, env_vars


class _MissingResolverVarsError(Exception):
    def __init__(self, missing_required_vars: list[str], missing_optional_vars: list[str], path: Path, rel_path: str):
        self.missing_required_vars = missing_required_vars
        self.missing_optional_vars = missing_optional_vars
        self.path = path
        self.rel_path = rel_path
        super().__init__(
            f"Missing variables: {missing_required_vars} for path: {path} with rel_path: {rel_path}, missing optional vars: {missing_optional_vars}"
        )

    def __str__(self) -> str:
        return f"Missing required variables: {self.missing_required_vars} for path: {self.path} with rel_path: {self.rel_path}, missing optional vars: {self.missing_optional_vars}"


class VariablesPlanResolver(Entity):
    paths: dict[str, list[ResolverVar]]
    repo_tfvars_paths: dict[str, dict[str, list[str]]] = Field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )

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

    def resolve_vars(self, repo_path: Path, path: Path, rel_path: str) -> tuple[list[Path], dict[str, ResolverVar]]:
        variables = find_variables_typed(path / "variables.tf")
        resolved_vars: dict[str, ResolverVar] = {}
        optional_vars: set[str] = set()
        for var in variables.values():
            for resolver_var in self.variable_path_matches(path, rel_path):
                if resolver_var.can_resolve(var):
                    resolved_vars[var.name] = resolver_var
            if var.is_default_set:
                optional_vars.add(var.name)
        repo_rel_path = str(path.relative_to(repo_path))
        repo_owner_project_name = owner_project_name(repo_path)
        matching_example_tfvars = sorted(
            repo_path / tfvars_path
            for tfvars_path, ws_paths in self.repo_tfvars_paths[repo_owner_project_name].items()
            if any(repo_rel_path.startswith(ws_path) for ws_path in ws_paths)
        )
        if matching_example_tfvars:
            return matching_example_tfvars, resolved_vars
        if missing_vars := set(variables.keys()) - set(resolved_vars.keys()):
            missing_required_vars = missing_vars - optional_vars
            missing_optional_vars = missing_vars & optional_vars
            if not missing_required_vars:
                logger.info(f"missing optional vars: {missing_optional_vars}")
                return [], resolved_vars
            raise _MissingResolverVarsError(
                sorted(missing_required_vars), sorted(missing_optional_vars), path, rel_path
            )
        return [], resolved_vars


class os_env_temp:
    def __init__(self, atlas_init_profiles_path: str):
        self.atlas_init_profiles_path = atlas_init_profiles_path

    def __enter__(self):
        if not self.atlas_init_profiles_path:
            return self
        path = self.atlas_init_profiles_path
        temp_static_dir = Path(path).parent.parent
        assert temp_static_dir.exists(), f"STATIC_DIR {temp_static_dir} does not exist"
        self.old_value = os.environ.get("STATIC_DIR", "")
        os.environ["STATIC_DIR"] = str(temp_static_dir)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not self.atlas_init_profiles_path:
            return
        if old := self.old_value:
            os.environ["STATIC_DIR"] = old
        else:
            os.environ.pop("STATIC_DIR", None)


def update_dumped_vars(path: Path, atlas_init_profiles_path: str) -> VariablesPlanResolver:
    with os_env_temp(atlas_init_profiles_path):
        atlas_init_settings = init_settings()
        loaded_env_vars = load_dotenv(atlas_init_settings.env_vars_vs_code)
        os.environ.update(loaded_env_vars)
        assert init_settings(AWSSettings, AtlasSettingsWithProject), "Settings must be initialized"
        project_settings = AtlasSettingsWithProject.from_env()
        dumped_vars = VariablesPlanResolver(
            repo_tfvars_paths={
                GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: {
                    "examples/migrate_cluster_to_advanced_cluster/module_user/v1_v2.tfvars": [
                        "examples/migrate_cluster_to_advanced_cluster/module_maintainer/v1",
                        "examples/migrate_cluster_to_advanced_cluster/module_maintainer/v2",
                        "examples/migrate_cluster_to_advanced_cluster/module_user/v1",
                        "examples/migrate_cluster_to_advanced_cluster/module_user/v2",
                    ],
                    "examples/migrate_cluster_to_advanced_cluster/module_user/v3.tfvars": [
                        "examples/migrate_cluster_to_advanced_cluster/module_maintainer/v3",
                        "examples/migrate_cluster_to_advanced_cluster/module_user/v3",
                    ],
                    "examples/migrate_cluster_to_advanced_cluster/module_user/v4.tfvars": [
                        "examples/migrate_cluster_to_advanced_cluster/module_maintainer/v4",
                        "examples/migrate_cluster_to_advanced_cluster/module_user/v4",
                    ],
                    "examples/migrate_team_project_assignment/example.auto.tfvars": [
                        "examples/migrate_team_project_assignment/",
                    ],
                    "examples/migrate_user_team_assignment/module_maintainer/v2/example.auto.tfvars": [
                        "examples/migrate_user_team_assignment/module_maintainer/v2"
                    ],
                },
            },
            paths={
                "*": [
                    ResolvedStringVar(
                        var_matches=["project*"],
                        value=project_settings.MONGODB_ATLAS_PROJECT_ID,
                    ),
                    ResolvedStringVar(
                        var_matches=["org*"],
                        value=project_settings.MONGODB_ATLAS_ORG_ID,
                    ),
                    ResolvedStringVar(
                        var_matches=["mongo_db_major_version"],
                        value="8.0",
                    ),
                    ResolvedStringVar(
                        var_matches=["cluster_type"],
                        value="REPLICASET",
                    ),
                    ResolvedStringVar(
                        var_matches=["instance_size"],
                        value="M30",
                    ),
                    ResolvedStringVar(
                        var_matches=["user_id"],
                        value=project_settings.MONGODB_ATLAS_PROJECT_OWNER_ID,
                    ),
                    ResolvedStringVar(
                        var_matches=["user_email", "username", "active_username", "pending_username"],
                        value=project_settings.MONGODB_ATLAS_USER_EMAIL,
                    ),
                    ResolvedListVar(
                        var_matches=["usernames"],
                        value=[project_settings.MONGODB_ATLAS_USER_EMAIL],
                    ),
                    ResolvedStringVar(
                        var_matches=["team_id", "team_id_1"],
                        value="68c28c58b5dd2d5956fe4b8c",  # TODO: get from env vars
                    ),
                    ResolvedStringVar(
                        var_matches=["team_id_2"],
                        value="68c29507b5dd2d595600b68b",  # TODO: get from env vars
                    ),
                    ResolvedStringVar(
                        var_matches=["team_name"],
                        value="plan-checks",  # TODO: get from env vars
                    ),
                    ResolvedEnvVar(
                        var_matches=["atlas_private_key", "private_key"],
                        sensitive=True,
                        value=project_settings.MONGODB_ATLAS_PRIVATE_KEY,
                        name="MONGODB_ATLAS_PRIVATE_KEY",
                    ),
                    ResolvedEnvVar(
                        var_matches=["atlas_public_key", "public_key"],
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
            },
        )
        yaml = dump(dumped_vars, "yaml")
        ensure_parents_write_text(path, yaml)
        return dumped_vars


_ignored_workspace_dirs = [
    ".terraform",
]


def include_path(rel_path: str) -> bool:
    return all(
        f"/{ignored_dir}/" not in rel_path and not rel_path.startswith(f"{ignored_dir}/")
        for ignored_dir in _ignored_workspace_dirs
    )


class TFWorkspaceRunState(Entity):
    command: str
    cwd: Path
    env: dict[str, str]
    tf_data_dir: Path

    def reproduce_path(self) -> Path:
        return self.tf_data_dir / "reproduce.sh"

    def reproduce_command(self) -> str:
        export_env = "\n".join(f'export {name}="{value}"' for name, value in self.env.items())
        script_shebang = "#!/bin/sh"
        return f"{script_shebang}\n{export_env}\ncd {self.cwd} && {self.command}"


class TFWorkspaceRunConfig(Entity):
    repo_path: Path
    path: Path
    rel_path: str
    resolved_vars: dict[str, Any]
    resolved_env_vars: dict[str, Any]
    base_tfvars: list[Path]

    run_state: TFWorkspaceRunState | None = Field(default=None, init=False)

    def tf_data_dir(self, settings: TfExtSettings) -> Path:
        assert self.path.is_relative_to(self.repo_path), f"path {self.path} is not relative to {self.repo_path}"
        repo_relative_path = self.path.relative_to(self.repo_path)
        repo_owner_project_name = owner_project_name(self.repo_path)
        return settings.static_root / "tf-ws-check" / repo_owner_project_name / repo_relative_path / ".terraform"

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
    atlas_init_profiles_path: str = typer.Option(
        "",
        "--atlas-init-profiles-path",
        help="Path to the atlas-init profiles directory. Used to resolve variables from .env-generated file",
    ),
):
    repo_path, rel_path = repo_path_rel_path()
    logger.warning(f"repo_path: {repo_path}, rel_path: {rel_path}")
    settings = init_tf_ext_settings()
    variable_resolvers = update_dumped_vars(settings.variable_plan_resolvers_dumped_file_path, atlas_init_profiles_path)
    manual_path = settings.variable_plan_resolvers_file_path
    if manual_path.exists():
        manual_resolvers = parse_model(manual_path, t=VariablesPlanResolver)
        variable_resolvers = variable_resolvers.merge(manual_resolvers)

    paths = sorted(
        (path.parent, rel_path)
        for path, rel_path in iter_paths_and_relative(root_path, "main.tf", only_files=True)
        if include_path(rel_path)
    )
    run_configs = []
    missing_vars_errors = []
    for path, rel_path in paths:
        try:
            base_tfvars, resolver_vars = variable_resolvers.resolve_vars(repo_path, path, rel_path)
            resolved_vars, resolved_env_vars = as_tfvars_env(resolver_vars)
            run_configs.append(
                TFWorkspaceRunConfig(
                    repo_path=repo_path,
                    path=path,
                    rel_path=rel_path,
                    resolved_vars=resolved_vars,
                    resolved_env_vars=resolved_env_vars,
                    base_tfvars=base_tfvars,
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

    def run_cmd(run_config: TFWorkspaceRunConfig) -> TFWorkspaceRunState | None:
        tf_vars_str = dump(run_config.resolved_vars, "pretty_json")
        tf_vars_path = run_config.tf_vars_path_json(settings)
        ensure_parents_write_text(tf_vars_path, tf_vars_str)
        tf_data_dir = run_config.tf_data_dir(settings)
        env_extra = run_config.resolved_env_vars | {"TF_DATA_DIR": str(run_config.tf_data_dir(settings))}

        lockfile_path = run_config.path / LOCKFILE_NAME
        if lockfile_path.exists():
            lockfile = parse_model(lockfile_path, t=Lockfile, format="json")
            logger.warning(f"Lockfile exists for {run_config.path}, skipping: {lockfile}")
            return None

        validate_tf_workspace(run_config.path, tf_cli_config_file=settings.tf_cli_config_file, env_extra=env_extra)
        if command == TFWsCommands.VALIDATE:
            return None
        command_extra = ""
        if command in {TFWsCommands.APPLY, TFWsCommands.DESTROY}:
            command_extra = " -auto-approve"

        base_var_files_str = ""
        if base_var_files := run_config.base_tfvars:
            base_var_files_str = " -var-file=" + " -var-file=".join(
                str(base_var_file) for base_var_file in base_var_files
            )
        terraform_full_command = f"terraform {command}{base_var_files_str} -var-file={tf_vars_path}{command_extra}"
        run_state = run_config.run_state = TFWorkspaceRunState(
            command=terraform_full_command,
            cwd=run_config.path,
            env=env_extra,
            tf_data_dir=tf_data_dir,
        )
        run_and_wait(
            run_state.command,
            cwd=run_state.cwd,
            env=run_state.env,
            user_input=run_count == 1,
        )
        return run_state

    with run_pool(f"{command} in TF Workspaces", total=run_count, max_concurrent_submits=9) as pool:
        futures: dict[Future[TFWorkspaceRunState | None], TFWorkspaceRunConfig] = {
            pool.submit(run_cmd, run_config): run_config for run_config in run_configs
        }
        for future, run_config in futures.items():
            try:
                future.result()
            except Exception as e:
                logger.error(f"Error running {command} for {run_config.path}: {e}")
                if run_state := run_config.run_state:
                    reproduce_sh = run_state.reproduce_path()
                    ensure_parents_write_text(reproduce_sh, run_state.reproduce_command())
                    logger.error(f"Reproduce command can be found in: {reproduce_sh}")
                continue
