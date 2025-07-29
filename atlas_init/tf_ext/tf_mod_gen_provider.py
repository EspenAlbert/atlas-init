from pathlib import Path
from ask_shell import run_pool
from model_lib import copy_and_validate, parse_model
import typer
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.models_module import (
    ModuleGenConfig,
    ProviderGenConfig,
    as_provider_name,
    import_resource_type_python_module,
)
from atlas_init.tf_ext.provider_schema import parse_atlas_schema
from atlas_init.tf_ext.settings import init_tf_ext_settings
from atlas_init.tf_ext.tf_mod_gen import finalize_and_validate_module, generate_resource_module

ATLAS_PROVIDER_PATH = "mongodb/mongodbatlas"


def tf_mod_gen_provider_resource_modules(
    provider_path: str = typer.Option(
        ATLAS_PROVIDER_PATH, "--provider-path", help="Provider path name, {owner}/{repo} from terraform registry"
    ),
):
    settings = init_tf_ext_settings()
    if provider_path != ATLAS_PROVIDER_PATH:
        raise NotImplementedError(f"provider_name must be {ATLAS_PROVIDER_PATH}")
    atlas_schema = parse_atlas_schema()
    resource_types = atlas_schema.resource_types
    repo_out = settings.repo_out
    provider_name = as_provider_name(provider_path)
    provider_config_path = repo_out.provider_settings_path(provider_name)
    provider_config = parse_model(provider_config_path, t=ProviderGenConfig)

    def generate_module(module_config: ModuleGenConfig) -> Path:
        resource = module_config.resources[0]
        generate_resource_module(module_config, resource.name, atlas_schema)
        module_path = finalize_and_validate_module(module_config)
        config_single = copy_and_validate(module_config, resources=[resource.single_variable_version()])
        python_module = import_resource_type_python_module(resource.name, module_config.dataclass_path(resource.name))
        variables_tf_single, _ = generate_module_variables(python_module, config_single.resource_config(resource.name))
        ensure_parents_write_text(module_path / "variables_single.tf", variables_tf_single)
        main_tf_single = generate_resource_main(python_module, config_single)
        ensure_parents_write_text(module_path / "main_single.tf", main_tf_single)
        return module_path

    with run_pool("Generating module files for resource types", total=len(resource_types)) as pool:
        for resource_type in resource_types:
            module_config = ModuleGenConfig.from_repo_out(resource_type, provider_config, repo_out)
            module_config.skip_python = True
            pool.submit(generate_module, module_config)
