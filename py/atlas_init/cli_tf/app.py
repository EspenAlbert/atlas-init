import logging
import sys

import typer
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.cli_tf.schema import (
    download_admin_api,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)
from atlas_init.cli_tf.schema_inspection import log_optional_only
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import init_settings

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command()
def schema():
    settings = init_settings()
    schema_out_path = settings.schema_out_path_computed
    schema_out_path.mkdir(exist_ok=True)

    schema_parsed = parse_py_terraform_schema(settings.tf_schema_config_path)
    generator_config = dump_generator_config(schema_parsed)
    generator_config_path = schema_out_path / "generator_config.yaml"
    generator_config_path.write_text(generator_config)
    provider_code_spec_path = schema_out_path / "provider-code-spec.json"
    admin_api_path = schema_out_path / "admin_api.yaml"
    if admin_api_path.exists():
        logger.warning(f"using existing admin api @ {admin_api_path}")
    else:
        download_admin_api(admin_api_path)

    if not run_binary_command_is_ok(
        cwd=schema_out_path,
        binary_name="tfplugingen-openapi",
        command=f"generate --config {generator_config_path.name} --output {provider_code_spec_path.name} {admin_api_path.name}",
        logger=logger,
    ):
        logger.critical("failed to generate spec")
        sys.exit(1)
    new_provider_spec = update_provider_code_spec(schema_parsed, provider_code_spec_path)
    provider_code_spec_path.write_text(new_provider_spec)
    logger.info(f"updated {provider_code_spec_path.name} ✅ ")

    go_code_output = schema_out_path / "internal"
    if go_code_output.exists():
        logger.warning(f"cleaning go code dir: {go_code_output}")
        clean_dir(go_code_output, recreate=True)

    if not run_binary_command_is_ok(
        cwd=schema_out_path,
        binary_name="tfplugingen-framework",
        command=f"generate resources --input ./{provider_code_spec_path.name} --output {go_code_output.name}",
        logger=logger,
    ):
        logger.critical("failed to generate plugin schema")
        sys.exit(1)

    logger.info(f"new files generated to {go_code_output} ✅")
    for go_file in sorted(go_code_output.rglob("*.go")):
        logger.info(f"new file @ '{go_file}'")


@app.command()
def schema_optional_only():
    repo_path = current_repo_path(Repo.TF)
    log_optional_only(repo_path)
