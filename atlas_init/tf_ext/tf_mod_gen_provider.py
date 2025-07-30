import logging
from pathlib import Path
from ask_shell import confirm, run_pool
from concurrent.futures import Future
from ask_shell.rich_live import get_live_console
from model_lib import copy_and_validate, parse_model
from rich.markdown import Markdown
import typer
from zero_3rdparty.file_utils import clean_dir

from atlas_init.tf_ext.models_module import (
    ModuleGenConfig,
    ProviderGenConfig,
    as_provider_name,
)
from atlas_init.tf_ext.provider_schema import parse_atlas_schema_from_settings
from atlas_init.tf_ext.settings import init_tf_ext_settings
from atlas_init.tf_ext.tf_mod_gen import finalize_and_validate_module, generate_resource_module

logger = logging.getLogger(__name__)
ATLAS_PROVIDER_PATH = "mongodb/mongodbatlas"


def tf_mod_gen_provider_resource_modules(
    provider_path: str = typer.Option(
        ATLAS_PROVIDER_PATH, "--provider-path", help="Provider path name, {owner}/{repo} from terraform registry"
    ),
    include_only: list[str] = typer.Option(
        ..., "-i", "--include-only", help="Only include these resource types", default_factory=list
    ),
):
    settings = init_tf_ext_settings()
    if provider_path != ATLAS_PROVIDER_PATH:
        raise NotImplementedError(f"provider_name must be {ATLAS_PROVIDER_PATH}")
    provider_name = as_provider_name(provider_path)
    repo_out = settings.repo_out
    provider_config_path = repo_out.provider_settings_path(provider_name)
    provider_config = parse_model(provider_config_path, t=ProviderGenConfig)

    atlas_schema = parse_atlas_schema_from_settings(settings, provider_config)
    include_only_set = set(include_only)
    deprecated_types = set(atlas_schema.deprecated_resource_types)

    def include_resource_type(resource_type: str) -> bool:
        return (not include_only or resource_type in include_only_set) and resource_type not in deprecated_types

    resource_types = [
        resource_type for resource_type in atlas_schema.resource_types if include_resource_type(resource_type)
    ]
    if not resource_types:
        raise ValueError(f"No resource types to generate for provider {provider_name} after filtering")

    def generate_module(module_config: ModuleGenConfig) -> tuple[Path, Path]:
        resource = module_config.resources[0]
        generate_resource_module(module_config, resource.name, atlas_schema)
        module_path = finalize_and_validate_module(module_config)

        config_single = copy_and_validate(
            module_config,
            resources=[resource.single_variable_version()],
            out_dir=module_path.with_name(module_path.stem + "_single"),
        )
        generate_resource_module(config_single, resource.name, atlas_schema)
        module_path_single = finalize_and_validate_module(config_single)
        return module_path, module_path_single

    with run_pool(
        "Generating module files for resource types", total=len(resource_types), exit_wait_timeout=60
    ) as pool:
        futures: dict[str, Future] = {}
        for resource_type in resource_types:
            module_config = ModuleGenConfig.from_repo_out(resource_type, provider_config, repo_out)
            module_config.skip_python = True
            futures[resource_type] = pool.submit(generate_module, module_config)
    summary = ["## Generated Resource Modules"]
    failures = []
    generated_module_paths: set[Path] = set()
    generated_py_files: set[Path] = set()
    for resource_type, future in futures.items():
        try:
            module_path, module_path_single = future.result()
            logger.info(f"Generated module for resource type = {resource_type} at {module_path} & {module_path_single}")
            summary.append(f"- {resource_type} -> {module_path}")
            generated_module_paths.add(module_path)
            generated_module_paths.add(module_path_single)
            generated_py_files.add(repo_out.dataclass_path(provider_name, resource_type))
        except Exception:
            failures.append(resource_type)
            logger.exception(f"failed to generate module for resource type = {resource_type}")
            continue
    if failures:
        summary.append("## Failed Resource Modules")
        for resource_type in failures:
            summary.append(f"- {resource_type}")
    get_live_console().print(Markdown("\n".join(summary)))
    if generated_module_paths:
        logger.info(f"Generated a total of: {len(generated_module_paths)} modules")
        if not include_only:
            clean_extra_modules(repo_out.resource_modules_provider_path(provider_name), generated_module_paths)
            clean_extra_py_modules(repo_out.py_provider_module(provider_name), generated_py_files)


def clean_extra_modules(resource_modules_out_dir: Path, generated_module_paths: set[Path]):
    if extra_paths := [
        path for path in resource_modules_out_dir.glob("*") if path.is_dir() and path not in generated_module_paths
    ]:
        logger.warning(f"Found extra paths in {resource_modules_out_dir}: {extra_paths}")
        extra_paths_str = "\n".join(path.name for path in extra_paths)
        if confirm(f"Can delete extra paths in {resource_modules_out_dir}:\n{extra_paths_str}"):
            for path in extra_paths:
                clean_dir(path, recreate=False)


def clean_extra_py_modules(py_modules_out_dir: Path, generated_py_files: set[Path]):
    if extra_paths := [
        path
        for path in py_modules_out_dir.glob("*.py")
        if path.is_file() and not path.name.startswith("_") and path not in generated_py_files
    ]:
        logger.warning(f"Found extra paths in {py_modules_out_dir}: {extra_paths}")
        extra_paths_str = "\n".join(path.name for path in extra_paths)
        if confirm(f"Can delete extra paths in {py_modules_out_dir}:\n{extra_paths_str}"):
            for path in extra_paths:
                path.unlink()
