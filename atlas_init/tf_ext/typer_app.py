from typer import Typer
from ask_shell import configure_logging


def typer_main():
    from atlas_init.tf_ext import tf_dep, tf_vars

    app = Typer(
        name="tf-ext",
        help="Terraform extension commands for Atlas Init",
    )
    app.command()(tf_dep.tf_dep)
    app.command(name="vars")(tf_vars.tf_vars)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
