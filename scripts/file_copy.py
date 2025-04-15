import logging
from pathlib import Path

import typer
from zero_3rdparty.file_utils import clean_dir, copy, iter_paths_and_relative

REL_PATH_FILES = [
    "atlas_init.yaml",
    "terraform.yaml",
    "tf/modules/cfn/assume_role_services.yaml",
    "tf/modules/cfn/resource_actions.yaml",
    "tf/.terraform.lock.hcl",
]

PY_PATH = REPO_PATH = Path(__file__).parent.parent
ATLAS_INIT_PATH = PY_PATH / "atlas_init"
logger = logging.getLogger(__name__)

app = typer.Typer()


@app.command(name="copy")
def _copy():
    for rel_path in REL_PATH_FILES:
        copy(REPO_PATH / rel_path, ATLAS_INIT_PATH / rel_path)
    for tf_path, tf_rel_path in iter_paths_and_relative(REPO_PATH / "tf", "*.tf", only_files=True):
        dest_path = ATLAS_INIT_PATH / "tf" / tf_rel_path
        copy(tf_path, dest_path)
    typer.echo("Copy complete: ✅")


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
