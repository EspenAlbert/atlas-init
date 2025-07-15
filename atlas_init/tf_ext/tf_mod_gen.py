import logging
from pathlib import Path

import typer
from ask_shell import new_task, run_and_wait
from model_lib import parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.models_module import ModuleGenConfig
from atlas_init.tf_ext.newres import prepare_newres
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_atlas_schema
from atlas_init.tf_ext.schema_to_dataclass import convert_and_format, import_resource_type_python_module
from atlas_init.tf_ext.settings import TfExtSettings

logger = logging.getLogger(__name__)


def tf_mod_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
    use_newres: bool = typer.Option(False, "--use-newres", help="Use newres to generate modules"),
    resource_type: list[str] = typer.Option("", "-r", "--resource-type", help="Resource types to generate modules for"),
    name: str = typer.Option("", "-n", "--name", help="Name of the module"),
    output_dir: Path | None = typer.Option(None, "-o", "--output-dir", help="Output directory for generated modules"),
):
    settings = TfExtSettings.from_env()
    assert tf_cli_config_file, "tf_cli_config_file is required"
    if use_newres:
        prepare_newres(settings.new_res_path)
    else:
        logger.info("will use Python generation")
        assert resource_type, "resource_type is required"
        config = ModuleGenConfig(
            resource_types=resource_type,
            settings=settings,
            output_dir=output_dir,
            name=name,
        )
        generate_module(config)


def generate_module(config: ModuleGenConfig) -> Path:
    with new_task("Reading Atlas Schema"):
        schema = parse_atlas_schema()
        assert schema
    resource_types = config.resource_types
    module_path = config.module_path
    with new_task("Generating module files for resource types", total=len(resource_types)) as task:
        for resource_type in resource_types:
            resource_type_schema = schema.raw_resource_schema.get(resource_type)
            assert resource_type_schema, f"resource type {resource_type} not found in schema"
            schema_parsed = parse_model(resource_type_schema, t=ResourceSchema)

            dataclass_path = module_path / f"{resource_type}.py"
            dataclass_code = convert_and_format(resource_type, schema_parsed, dataclass_path)
            ensure_parents_write_text(dataclass_path, dataclass_code)

            python_module = import_resource_type_python_module(resource_type, dataclass_path)
            main_tf = generate_resource_main(python_module, config)
            main_path = config.main_tf_path(resource_type)
            ensure_parents_write_text(main_path, main_tf)

            variablesx_tf, variables_tf = generate_module_variables(python_module, config)
            variables_path = config.variables_path(resource_type)
            if variablesx_tf and variables_tf:
                variablesx_path = config.variablesx_path(resource_type)
                ensure_parents_write_text(variablesx_path, variablesx_tf)
                ensure_parents_write_text(variables_path, variables_tf)
            else:
                ensure_parents_write_text(variables_path, variablesx_tf)
            task.update(advance=1)
    provider_path = module_path / "providers.tf"
    if not provider_path.exists():
        with new_task("Generating providers.tf"):
            ensure_parents_write_text(provider_path, schema.providers_tf)
    if auto_tfvars := config.auto_tfvars:
        with new_task("Generating auto.tfvars"):
            ensure_parents_write_text(module_path / "vars.auto.tfvars", auto_tfvars)
    terraform_commands = [
        "terraform init",
        "terraform fmt .",
        "terraform validate .",
        "terraform plan",
    ]
    logger.info(f"Module dumped to {module_path}, running checks")
    with new_task("Terraform Sanity Checks", total=len(terraform_commands)) as task:
        for command in terraform_commands:
            run_and_wait(command, cwd=module_path)
            task.update(advance=1)
    return module_path
