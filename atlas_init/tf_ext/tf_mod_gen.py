import difflib
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import typer
from ask_shell import new_task, run_and_wait, run_pool, text
from model_lib import parse_model, parse_payload
from pydantic import DirectoryPath, TypeAdapter
from zero_3rdparty.file_utils import clean_dir, copy, ensure_parents_write_text

from atlas_init.cli_tf.example_update import UpdateExamples, update_examples
from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG
from atlas_init.tf_ext.gen_examples import generate_module_examples, read_example_dirs
from atlas_init.tf_ext.gen_module_readme import generate_readme
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_output import generate_resource_output
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.gen_versions import dump_versions_tf
from atlas_init.tf_ext.models_module import (
    MissingDescriptionError,
    ModuleGenConfig,
    import_resource_type_python_module,
    parse_attribute_descriptions,
    store_updated_attribute_description,
)
from atlas_init.tf_ext.newres import prepare_newres
from atlas_init.tf_ext.plan_diffs import (
    ExamplePlanCheck,
    generate_expected_actual,
    parse_plan_output,
    read_variables_path,
)
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_atlas_schema
from atlas_init.tf_ext.schema_to_dataclass import convert_and_format
from atlas_init.tf_ext.settings import TfExtSettings

logger = logging.getLogger(__name__)


def tf_mod_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
    use_newres: bool = typer.Option(False, "--use-newres", help="Use newres to generate modules"),
    resource_type: list[str] = typer.Option(
        ..., "-r", "--resource-type", help="Resource types to generate modules for", default_factory=list
    ),
    name: str = typer.Option("", "-n", "--name", help="Name of the module"),
    in_dir: DirectoryPath = typer.Option(
        ..., "-i", "--in-dir", help="Parent directory where the module generation files are stored"
    ),
    out_dir: DirectoryPath = typer.Option(
        ...,
        "-o",
        "--out-dir",
        help="Output directory for generated modules, the module will end up in {output_dir}/{name}",
    ),
    example_var_file: Path = typer.Option(
        ..., "-e", "--example-var-file", help="Path to example variable file", envvar="TF_EXT_EXAMPLE_VAR_FILE"
    ),
):
    settings = TfExtSettings.from_env()
    assert tf_cli_config_file, "tf_cli_config_file is required"
    if use_newres:
        prepare_newres(settings.new_res_path)
    else:
        settings = TfExtSettings.from_env()
        logger.info("will use Python generation")
        config = ModuleGenConfig.from_paths(name, in_dir, out_dir, settings)
        prepare_out_dir(config)
        generate_module(config)
        module_examples_and_readme(config, example_var_file=example_var_file)


def prepare_out_dir(config: ModuleGenConfig, *, skip_clean_dir: bool = False):
    if not skip_clean_dir:
        clean_dir(config.module_out_path)
    in_dir = config.in_dir
    assert in_dir, "in_dir is required"
    for src_file in in_dir.glob("*"):
        if config.skip_copy(src_file):
            continue
        copy(src_file, config.module_out_path / src_file.name, clean_dest=True)  # also copies directories
    example_checks = config.example_plan_checks_path
    if example_checks.exists():
        example_plan_checks_raw = parse_payload(example_checks)
        config.example_plan_checks = TypeAdapter(list[ExamplePlanCheck]).validate_python(example_plan_checks_raw)


def generate_module(config: ModuleGenConfig) -> Path:
    with new_task("Reading Atlas Schema"):
        schema = parse_atlas_schema()
        assert schema
    resource_types = config.resource_types
    module_path = config.module_out_path
    with new_task("Generating module files for resource types", total=len(resource_types)) as task:
        for resource_type in resource_types:
            resource_type_schema = schema.raw_resource_schema.get(resource_type)
            assert resource_type_schema, f"resource type {resource_type} not found in schema"
            schema_parsed = parse_model(resource_type_schema, t=ResourceSchema)

            dataclass_path = config.dataclass_path(resource_type)
            dataclass_code = convert_and_format(resource_type, schema_parsed, config, existing_path=dataclass_path)
            ensure_parents_write_text(dataclass_path, dataclass_code)

            python_module = import_resource_type_python_module(resource_type, dataclass_path)
            main_tf = generate_resource_main(python_module, config)
            main_path = config.main_tf_path(resource_type)
            ensure_parents_write_text(main_path, main_tf)

            variablesx_tf, variables_tf = generate_module_variables(
                python_module, config.resource_config(resource_type)
            )
            variables_path = config.variables_path(resource_type)
            if variablesx_tf and variables_tf:
                variablesx_path = config.variablesx_path(resource_type)
                ensure_parents_write_text(variablesx_path, variablesx_tf)
                ensure_parents_write_text(variables_path, variables_tf)
            else:
                ensure_parents_write_text(variables_path, variablesx_tf)
            task.update(advance=1)
            if output_tf := generate_resource_output(python_module, config):
                output_path = config.output_path(resource_type)
                ensure_parents_write_text(output_path, output_tf)
            if config.skip_python:
                dataclass_path.unlink(missing_ok=True)

    dump_versions_tf(config.module_out_path, skip_python=config.skip_python)
    logger.info(f"Module dumped to {config.module_out_path}, running checks")
    validate_module(config.module_out_path)
    return module_path


OUT_BINARY_PATH = "tfplan.binary"


def validate_module(tf_workdir: Path):
    terraform_commands = [
        "terraform init",
        "terraform fmt .",
        "terraform validate .",
    ]
    with new_task("Terraform Module Validate Checks", total=len(terraform_commands)) as task:
        for command in terraform_commands:
            run_and_wait(command, cwd=tf_workdir)
            task.update(advance=1)


def module_examples_and_readme(config: ModuleGenConfig, *, example_var_file: Path | None = None) -> Path:
    path = config.module_out_path
    if (examples_test := config.examples_test_path) and examples_test.exists():
        with new_task(f"Generating examples from {config.FILENAME_EXAMPLES_TEST}"):
            assert len(config.resource_types) == 1
            resource_type = config.resource_types[0]
            py_module = import_resource_type_python_module(resource_type, config.dataclass_path(resource_type))
            examples_generated = generate_module_examples(config, py_module, resource_type=resource_type)
        if examples_generated:
            with run_pool("Validating examples", total=len(examples_generated), exit_wait_timeout=60) as pool:
                for example_path in examples_generated:
                    pool.submit(validate_module, example_path)

    attribute_descriptions = parse_attribute_descriptions(config.settings)
    settings = config.settings

    def new_description(name: str, old_description: str, path: Path) -> str:
        resource_type = config.resolve_resource_type(path)
        try:
            return attribute_descriptions.resolve_description(name, resource_type)
        except MissingDescriptionError:
            if new_text := text(
                f"Enter description for variable/output {name} in {resource_type} for {path} (empty to skip)",
                default="",
            ):
                store_updated_attribute_description(attribute_descriptions, settings, name, new_text, resource_type)
            return new_text

    out_event = update_examples(
        UpdateExamples(
            examples_base_dir=path,
            skip_tf_fmt=True,
            new_description_call=new_description,
        )
    )
    if out_event.changes:
        logger.info(f"Updated attribute descriptions: {len(out_event.changes)}")
        run_and_wait("terraform fmt -recursive .", cwd=path, ansi_content=False, allow_non_zero_exit=True)
    if readme_path := config.readme_path():
        with new_task("Generating README.md"):
            readme_content = generate_readme(config)
            ensure_parents_write_text(readme_path, readme_content)
    if example_var_file:
        examples = read_example_dirs(config.module_out_path)
        if examples:
            failed_examples: list[Path] = []
            with run_pool("Running terraform plan on examples", total=len(examples), exit_wait_timeout=60) as pool:

                def run_example(example: Path):
                    try:
                        run_and_wait(f"terraform plan -var-file={example_var_file}", cwd=example)
                    except Exception as e:
                        logger.error(f"Failed to run terraform plan on {example.name}: {e}")
                        failed_examples.append(example)

                for example in examples:
                    pool.submit(run_example, example)
            if failed_examples:
                failed_str = ", ".join(sorted(example.name for example in failed_examples))
                logger.error(f"Failed to run terraform plan on {failed_str} examples")
    return path


def example_plan_checks(config: ModuleGenConfig, timeout_all_seconds: int = 60) -> list[Path]:
    example_checks = config.example_plan_checks
    settings = config.settings

    def run_check(check: ExamplePlanCheck):
        expected_dir = settings.output_plan_dumps / check.expected_output_dir_name
        variables_path = read_variables_path(expected_dir)
        with TemporaryDirectory() as temp_dir:
            stored_plan = Path(temp_dir) / "plan.json"
            tf_dir = config.example_path(check.example_name)
            validate_module(tf_dir)
            var_arg = f" -var-file={variables_path}" if variables_path else ""
            run_and_wait(f"terraform plan -out={OUT_BINARY_PATH}{var_arg}", cwd=tf_dir)
            run_and_wait(f"terraform show -json {OUT_BINARY_PATH} > {stored_plan}", cwd=tf_dir)
            plan_output = parse_plan_output(stored_plan)
        return generate_expected_actual(settings.output_plan_dumps, check, plan_output)

    with run_pool("Run Examples", total=len(example_checks), exit_wait_timeout=timeout_all_seconds) as pool:
        futures = {pool.submit(run_check, check): check for check in example_checks}
    diff_paths: list[Path] = []
    for future in futures:
        check = futures[future]
        try:
            expected, actual = future.result(timeout=timeout_all_seconds)
            if expected != actual:
                diff_path = settings.plan_diff_output_path / f"{config.name}_{check.example_name}.html"
                dump_html_diff(expected, actual, diff_path)
                diff_paths.append(diff_path)
                logger.error(f"Example check failed for {check}")
        except Exception as e:
            logger.error(f"Example check failed to run terraform commands for {check}: {e}")
            raise e
    return diff_paths


def dump_html_diff(expected: str, actual: str, diff_path: Path) -> str:
    html_text = difflib.HtmlDiff().make_file(
        expected.splitlines(),
        actual.splitlines(),
        "expected",
        "actual",
    )
    ensure_parents_write_text(diff_path, html_text)
    return html_text
