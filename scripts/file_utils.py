import logging
from pathlib import Path

import typer
from zero_3rdparty.file_utils import clean_dir, copy, iter_paths_and_relative

from atlas_init.cli_tf.hcl.modifier import read_block_attribute_object_keys

REL_PATH_FILES = [
    "atlas_init.yaml",
    "terraform.yaml",
    "tf/modules/cfn/assume_role_services.yaml",
    "tf/modules/cfn/resource_actions.yaml",
    "tf/.terraform.lock.hcl",
]

REPO_PATH = Path(__file__).parent.parent
ATLAS_INIT_PATH = REPO_PATH / "atlas_init"
TF_SRC_PATH = REPO_PATH / "tf"
logger = logging.getLogger(__name__)

app = typer.Typer()


@app.command(name="copy")
def _copy():
    for rel_path in REL_PATH_FILES:
        copy(REPO_PATH / rel_path, ATLAS_INIT_PATH / rel_path)
    for tf_path, tf_rel_path in iter_paths_and_relative(TF_SRC_PATH, "*.tf", only_files=True):
        dest_path = ATLAS_INIT_PATH / "tf" / tf_rel_path
        copy(tf_path, dest_path)
    typer.echo("Copy complete: ✅")


@app.command()
def generate():
    module_name_env_vars: dict[str, list[str]] = {}
    for tf_path in TF_SRC_PATH.glob("modules/*/*.tf"):
        if env_vars := read_block_attribute_object_keys(
            tf_path,
            block_type="output",
            block_name="env_vars",
            block_key="value",
        ):
            module_name_env_vars[tf_path.parent.name] = env_vars
    if not module_name_env_vars:
        logger.warning("no env vars found in modules")
        return
    generated_py = [
        "from atlas_init.settings.env_vars_generated import _EnvVarsGenerated",
        "",
        "",
    ]
    for name in sorted(module_name_env_vars.keys()):
        env_vars = module_name_env_vars[name]
        generated_py.append(f"class TFModule{name.title()}(_EnvVarsGenerated):")
        generated_py.extend(f"    {env_var}: str" for env_var in sorted(env_vars))
        generated_py.extend(["", ""])
    generated_py.pop()  # remove last empty line
    generated_py_str = "\n".join(generated_py)
    generated_py_path = ATLAS_INIT_PATH / "settings" / "env_vars_modules.py"
    generated_py_path.write_text(generated_py_str)


@app.command(name="clean")
def clean():
    for rel_path in REL_PATH_FILES:
        dest_path = ATLAS_INIT_PATH / rel_path
        if dest_path.exists():
            dest_path.unlink()
    if (ATLAS_INIT_PATH / "tf").exists():
        clean_dir(ATLAS_INIT_PATH / "tf", recreate=False)
    typer.echo("Clean complete: ✅")


if __name__ == "__main__":
    app()
