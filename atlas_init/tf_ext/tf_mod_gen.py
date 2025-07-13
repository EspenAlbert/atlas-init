from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.newres import prepare_newres
from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG


def tf_mod_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
):
    settings = TfExtSettings.from_env()
    assert tf_cli_config_file, "tf_cli_config_file is required"
    prepare_newres(settings.new_res_path)
