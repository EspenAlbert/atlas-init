from ask_shell import configure_logging
from typer import Typer

from atlas_init.tf_ext import api_call


def typer_main():
    from atlas_init.tf_ext import tf_dep, tf_modules, tf_vars

    app = Typer(
        name="tf-ext",
        help="Terraform extension commands for Atlas Init",
    )
    app.command(name="dep-graph")(tf_dep.tf_dep_graph)
    app.command(name="vars")(tf_vars.tf_vars)
    app.command(name="modules")(tf_modules.tf_modules)
    app.command(name="api")(api_call.api)
    app.command(name="api-config")(api_call.api_config)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
