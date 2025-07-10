import typer


def default_skippped_directories() -> list[str]:
    return [
        "prometheus-and-teams",  #  Provider registry.terraform.io/hashicorp/template v2.2.0 does not have a package available for your current platform, darwin_arm64.
    ]


REPO_PATH_ARG = typer.Argument(help, help="Path to the mongodbatlas-terraform-provider repository")
SKIP_EXAMPLES_DIRS_OPTION = typer.Option(
    ...,
    "--skip-examples",
    help="Skip example directories with these names",
    default_factory=default_skippped_directories,
    show_default=True,
)
