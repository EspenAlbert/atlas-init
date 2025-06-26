from ask_shell import configure_logging
from typer import Typer


def typer_main():
    from atlas_init.tf_ext import tf_dep, tf_vars, tf_modules

    app = Typer(
        name="tf-ext",
        help="Terraform extension commands for Atlas Init",
    )
    app.command(name="dep-graph")(tf_dep.tf_dep_graph)
    app.command(name="vars")(tf_vars.tf_vars)
    app.command(name="modules")(tf_modules.tf_modules)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
