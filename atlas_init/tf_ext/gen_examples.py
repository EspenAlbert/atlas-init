from contextlib import suppress
from dataclasses import asdict
from functools import singledispatch
from pathlib import Path

from zero_3rdparty import humps
from zero_3rdparty.file_utils import clean_dir, ensure_parents_write_text

from atlas_init.tf_ext.gen_resource_variables import generate_resource_variables
from atlas_init.tf_ext.gen_versions import dump_versions_tf
from atlas_init.tf_ext.models_module import ModuleGenConfig, ResourceAbs, ResourceTypePythonModule
from atlas_init.tf_ext.py_gen import import_module_by_using_parents

VARIABLE_PLACEHOLDER = "var."
INDENT = "    "


def _examples_casted(examples: dict) -> dict[str, ResourceAbs]:
    return examples


def read_example_dirs(module_path: Path) -> list[Path]:
    return sorted(
        example_dir
        for example_dir in (module_path / "examples").glob("*")
        if example_dir.is_dir()
        and len(example_dir.name) > 2
        and example_dir.name[:2].isdigit()
        and (example_dir / "main.tf").exists()
    )


def generate_module_examples(
    config: ModuleGenConfig, module: ResourceTypePythonModule, *, skip_clean_dir: bool = False
) -> list[Path]:
    test_path = config.examples_test_path
    imported_module = import_module_by_using_parents(test_path)
    examples = getattr(imported_module, "EXAMPLES")
    assert isinstance(examples, dict), f"{imported_module} does not have an EXAMPLES attribute"
    examples_parsed = _examples_casted(examples)
    examples_generated: list[Path] = []
    for example_name, example in examples_parsed.items():
        dumped_resource = {k: v for k, v in asdict(example).items() if v is not None}
        variables = {
            k: f"{v}{k}"
            for k, v in dumped_resource.items()
            if isinstance(v, str) and v.startswith(VARIABLE_PLACEHOLDER)
        }
        dumped_resource |= variables
        variable_names = set(variables.keys())
        ignored_names = set(module.all_field_names) - variable_names
        ignored_names |= module.all_skip_variables
        resource_cls = module.resource_ext or module.resource
        assert resource_cls, f"{module} does not have a resource class"
        example_path = config.example_path(example_name)
        if not skip_clean_dir and example_path.exists():
            clean_dir(example_path)

        variables_tf = generate_resource_variables(resource_cls, ignored_names, required_variables=variable_names)
        ensure_parents_write_text(example_path / "variables.tf", variables_tf)
        variables_str = "\n".join(f"{k} = {dump_variable(v)}" for k, v in dumped_resource.items() if can_dump(v))
        example_main = example_main_tf(config, variables_str)
        ensure_parents_write_text(example_path / "main.tf", example_main)
        dump_versions_tf(example_path, skip_python=config.skip_python, minimal=True)
        examples_generated.append(example_path)
    return examples_generated


class NotDumpableError(Exception):
    def __init__(self, value: object) -> None:
        super().__init__(f"Cannot dump variable {value!r}")


def can_dump(variable: object) -> bool:
    with suppress(NotDumpableError):
        dump_variable(variable)
        return True
    return False


@singledispatch
def dump_variable(variable: object) -> str:
    raise NotDumpableError(variable)


@dump_variable.register
def dump_variable_str(variable: str) -> str:
    if "." in variable:
        return variable
    return f'"{variable}"'


@dump_variable.register
def dump_variable_int(variable: int) -> str:
    return str(variable)


@dump_variable.register
def dump_variable_float(variable: float) -> str:
    return str(variable)


@dump_variable.register
def dump_variable_bool(variable: bool) -> str:
    return "true" if variable else "false"


@dump_variable.register
def dump_variable_list(variable: list) -> str:
    return f"[\n{', '.join(f'{INDENT}{dump_variable(nested)}' for nested in variable if can_dump(nested))}\n]"


@dump_variable.register
def dump_variable_set(variable: set) -> str:
    return f"[\n{', '.join(f'{INDENT}{dump_variable(nested)}' for nested in variable if can_dump(nested))}\n]"


@dump_variable.register
def dump_variable_dict(variable: dict) -> str:
    return "{\n" + "\n".join(f"{INDENT}{k} = {dump_variable(v)}" for k, v in variable.items() if can_dump(v)) + "\n}"


def example_main_tf(module: ModuleGenConfig, variables: str) -> str:
    variables_indented = "\n".join(f"{INDENT}{var}" for var in variables.split("\n"))
    module_name_snake = humps.dekebabize(module.name)
    return f"""\
module "{module_name_snake}" {{
    source = "../.."

{variables_indented}
}}
"""
