import logging
from os import getenv
from pathlib import Path

from model_lib import dump, parse_model, parse_payload
import typer
from lark.exceptions import VisitError
from zero_3rdparty.file_utils import clean_dir, copy, iter_paths_and_relative
from zero_3rdparty.dict_nested import read_nested

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.cli_tf.hcl.modifier import read_block_attribute_object_keys, safe_parse
from atlas_init.cli_tf.hcl.modifier2 import (
    AttributeChange,
    attribute_transfomer,
    update_attribute_object_str_value_for_block,
    write_tree,
)
from atlas_init.repos.cfn import cfn_examples_dir
from atlas_init.settings.config import AtlasInitConfig
from atlas_init.settings.rich_utils import configure_logging

REL_PATH_FILES = [
    "atlas_init.yaml",
    "terraform.yaml",
    "tf/modules/cfn/assume_role_services.yaml",
    "tf/modules/cfn/resource_actions.yaml",
    "tf/.terraform.lock.hcl",
]

REPO_PATH = Path(__file__).parent.parent
ATLAS_INIT_PATH = REPO_PATH / "atlas_init"
ATLAS_INIT_CONFIG_PATH = REPO_PATH / "atlas_init.yaml"
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
    generate_env_vars_modules()


def generate_env_vars_modules():
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


@app.command()
def check():
    old = ATLAS_INIT_CONFIG_PATH.read_text()
    config = parse_model(ATLAS_INIT_CONFIG_PATH, t=AtlasInitConfig)
    config.test_suites = sorted(config.test_suites)
    config_raw = config.model_dump(exclude_defaults=True, exclude_none=True)
    new = dump(config_raw, "yaml")
    if old == new:
        typer.echo(f"config is sorted ✅ @ {ATLAS_INIT_CONFIG_PATH.name}")
    else:
        typer.echo(f"config is not sorted ❌ {ATLAS_INIT_CONFIG_PATH.name}")
        ATLAS_INIT_CONFIG_PATH.write_text(new)
    repo_path_cfn = getenv("REPO_PATH_CFN")
    if not repo_path_cfn:
        logger.warning("REPO_PATH_CFN not set")
        return
    check_execution_role(Path(repo_path_cfn))


def check_execution_role(repo_path: Path) -> None:
    execution_role = cfn_examples_dir(repo_path) / "execution-role.yaml"
    execution_raw = parse_payload(execution_role)
    actions_expected = read_nested(
        execution_raw,
        "Resources.ExecutionRole.Properties.Policies.[0].PolicyDocument.Statement.[0].Action",
    )
    actions_found = parse_payload(TF_SRC_PATH / "modules/cfn/resource_actions.yaml")
    if diff := set(actions_expected) ^ set(actions_found):
        raise ValueError(f"non-matching execution role actions: {sorted(diff)}")
    services_found = parse_payload(TF_SRC_PATH / "modules/cfn/assume_role_services.yaml")
    services_expected = read_nested(
        execution_raw,
        "Resources.ExecutionRole.Properties.AssumeRolePolicyDocument.Statement.[0].Principal.Service",
    )
    if diff := set(services_found) ^ set(services_expected):
        raise ValueError(f"non-matching execution role services: {sorted(diff)}")
    typer.echo(f"execution role in modules/cfn is up to date with {execution_role} ✅")


@app.command(name="clean")
def clean():
    for rel_path in REL_PATH_FILES:
        dest_path = ATLAS_INIT_PATH / rel_path
        if dest_path.exists():
            dest_path.unlink()
    if (ATLAS_INIT_PATH / "tf").exists():
        clean_dir(ATLAS_INIT_PATH / "tf", recreate=False)
    typer.echo("Clean complete: ✅")


@app.command()
def provider_version(
    atlas_version: str = typer.Option(
        "1.33", "--atlas-version", "-a", help="MongoDB Atlas Terraform provider version upgrade"
    ),
):
    all_changes: list[AttributeChange] = []
    for tf_path, _ in iter_paths_and_relative(TF_SRC_PATH, "*.tf"):
        tree = safe_parse(tf_path)
        assert tree, f"failed to parse provider.tf @ {tf_path}"
        version_transformer, version_changes = attribute_transfomer("mongodbatlas", "version", atlas_version)
        try:
            new_tree = update_attribute_object_str_value_for_block(tree, "terraform", version_transformer)
        except VisitError as e:
            logger.warning(f"failed to update {tf_path}: {e}")
            continue
        if not version_changes:
            continue
        all_changes.extend(version_changes)
        for version_change in version_changes:
            logger.info(f"updating {tf_path} with {version_change.old_value} -> {version_change.new_value}")
        new_tf = write_tree(new_tree)
        tf_path.write_text(new_tf)
    if all_changes:
        logger.info(f"updated {len(all_changes)} provider.tf files, formatting")
        run_binary_command_is_ok("terraform", "fmt -recursive .", cwd=TF_SRC_PATH, logger=logger)
    else:
        logger.info("no provider.tf files updated")


if __name__ == "__main__":
    configure_logging(app, log_level="INFO")
    app()
