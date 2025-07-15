import logging
from pathlib import Path

from ask_shell import run_and_wait
from model_lib import parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_resource_variables
from atlas_init.tf_ext.schema_to_dataclass import convert_and_format, import_resource_type_dataclass
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.newres import prepare_newres
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_atlas_schema
from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG
import typer

logger = logging.getLogger(__name__)


def tf_mod_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
    use_newres: bool = typer.Option(False, "--use-newres", help="Use newres to generate modules"),
    resource_type: str = typer.Option("", "--resource-type", help="Resource type to generate modules for"),
):
    settings = TfExtSettings.from_env()
    assert tf_cli_config_file, "tf_cli_config_file is required"
    if use_newres:
        prepare_newres(settings.new_res_path)
    else:
        logger.info("will use Python generation")
        assert resource_type, "resource_type is required"
        generate_module(resource_type, settings)


def generate_module(resource_type: str, settings: TfExtSettings) -> Path:
    schema = parse_atlas_schema()
    assert schema
    resource_type_schema = schema.raw_resource_schema.get(resource_type)
    assert resource_type_schema, f"resource type {resource_type} not found in schema"
    schema_parsed = parse_model(resource_type_schema, t=ResourceSchema)
    dataclass_code = convert_and_format(resource_type, schema_parsed)
    module_path = settings.module_resource_type(resource_type)
    dataclass_path = module_path / f"{resource_type}.py"
    ensure_parents_write_text(dataclass_path, dataclass_code)
    resource = import_resource_type_dataclass(resource_type, dataclass_path)
    main_tf = generate_resource_main(resource_type, resource)
    main_path = module_path / f"{resource_type}.tf"
    ensure_parents_write_text(main_path, main_tf)

    variables_tf = generate_resource_variables(resource)
    variables_path = module_path / f"{resource_type}_variables.tf"
    ensure_parents_write_text(variables_path, variables_tf)
    provider_path = module_path / "providers.tf"
    if not provider_path.exists():
        ensure_parents_write_text(provider_path, schema.providers_tf)
    run_and_wait("terraform init", cwd=module_path)
    run_and_wait("terraform fmt .", cwd=module_path)
    run_and_wait("terraform validate .", cwd=module_path)
    run_and_wait("terraform plan", cwd=module_path)
    return module_path
