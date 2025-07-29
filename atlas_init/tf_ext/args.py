import typer


def default_skippped_directories() -> list[str]:
    return [
        "prometheus-and-teams",  #  Provider registry.terraform.io/hashicorp/template v2.2.0 does not have a package available for your current platform, darwin_arm64.
    ]


REPO_PATH_ATLAS_ARG = typer.Argument(..., help="Path to the mongodbatlas-terraform-provider repository")
SKIP_EXAMPLES_DIRS_OPTION = typer.Option(
    ...,
    "--skip-examples",
    help="Skip example directories with these names",
    default_factory=default_skippped_directories,
    show_default=True,
)
TF_CLI_CONFIG_FILE_ENV_NAME = "TF_CLI_CONFIG_FILE"
TF_CLI_CONFIG_FILE_ARG = typer.Option(
    "",
    "-tf-cli",
    "--tf-cli-config-file",
    envvar=TF_CLI_CONFIG_FILE_ENV_NAME,
    help="Terraform CLI config file",
)
ENV_NAME_REPO_PATH_ATLAS_PROVIDER = "REPO_PATH_ATLAS_PROVIDER"
TF_REPO_PATH_ATLAS = typer.Option(
    "",
    "--tf-repo-path-atlas",
    help="Path to the mongodbatlas-terraform-provider repository",
    envvar=ENV_NAME_REPO_PATH_ATLAS_PROVIDER,
)
