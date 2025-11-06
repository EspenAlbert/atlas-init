from typer import Typer

from atlas_init.settings.rich_utils import configure_logging


def typer_main():
    from atlas_init.sdk_ext import go

    app = Typer(
        name="sdk-ext",
        help="SDK extension commands for Atlas Init",
    )
    app.command(name="go")(go.go)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
