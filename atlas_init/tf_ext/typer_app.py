from ask_shell import configure_logging
from typer import Typer

from atlas_init.tf_ext import api_call, settings, tf_desc_gen, tf_example_readme, tf_mod_gen_provider, tf_ws


def typer_main():
    from atlas_init.tf_ext import tf_dep, tf_mod_gen, tf_modules, tf_vars

    app = Typer(
        name="tf-ext",
        help="Terraform extension commands for Atlas Init",
    )
    app.command(name="dep-graph")(tf_dep.tf_dep_graph)
    app.command(name="vars")(tf_vars.tf_vars)
    app.command(name="modules")(tf_modules.tf_modules)
    app.command(name="mod-gen")(tf_mod_gen.tf_mod_gen)
    app.command(name="desc-gen")(tf_desc_gen.tf_desc_gen)
    app.command(name="api")(api_call.api)
    app.command(name="api-config")(api_call.api_config)
    app.command(name="mod-gen-provider")(tf_mod_gen_provider.tf_mod_gen_provider_resource_modules)
    app.command(name="check-env-vars")(settings.init_tf_ext_settings)
    app.command(name="example-readme")(tf_example_readme.tf_example_readme)
    app.command(name="ws")(tf_ws.tf_ws)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
