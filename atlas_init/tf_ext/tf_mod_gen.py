import logging
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.newres import prepare_newres
from atlas_init.tf_ext.provider_schema import parse_atlas_schema
from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG
import typer

logger = logging.getLogger(__name__)


def tf_mod_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
    use_newres: bool = typer.Option(False, "--use-newres", help="Use newres to generate modules"),
):
    settings = TfExtSettings.from_env()
    assert tf_cli_config_file, "tf_cli_config_file is required"
    if use_newres:
        prepare_newres(settings.new_res_path)
    else:
        logger.info("will use Python generation")
        generate_modules()


def generate_modules():
    schema = parse_atlas_schema()
    assert schema
