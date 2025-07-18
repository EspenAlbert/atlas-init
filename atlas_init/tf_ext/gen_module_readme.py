import logging
from enum import StrEnum

from ask_shell import run_and_wait
from zero_3rdparty.file_utils import ensure_parents_write_text, update_between_markers
from atlas_init.tf_ext.models_module import ModuleGenConfig

logger = logging.getLogger(__name__)
_readme_disclaimer = """\
## Disclaimer
This Module is not meant for external consumption.
It is part of a development PoC.
Any usage problems will not be supported.
However, if you have any ideas or feedback feel free to open a Github Issue!
"""


class ReadmeMarkers(StrEnum):
    DISCLAIMER = "DISCLAIMER"
    EXAMPLE = "TF_EXAMPLES"
    TF_DOCS = "TF_DOCS"

    @classmethod
    def as_start(cls, marker_name: str) -> str:
        return f"<!-- BEGIN_{marker_name} -->"

    @classmethod
    def as_end(cls, marker_name: str) -> str:
        return f"<!-- END_{marker_name} -->"

    @classmethod
    def marker_lines(cls, marker_name: str) -> str:
        return f"""\
{cls.as_start(marker_name)}

{cls.as_end(marker_name)}
"""

    @classmethod
    def example_boilerplate(cls) -> str:
        return "\n".join(cls.marker_lines(marker_name) for marker_name in list(cls))


def example_main_tf(module: ModuleGenConfig, variables: str) -> str:
    variables_indented = "\n".join(f"    {var}" for var in variables.split("\n"))
    return f"""\
module "{module.name}" {{
    {variables_indented}
}}"""


def read_examples(module: ModuleGenConfig) -> str:
    example_dirs = sorted(
        example_dir
        for example_dir in module.examples_path.glob("*")
        if example_dir.is_dir() and len(example_dir.name) > 2 and example_dir.name[:2].isdigit()
    )
    content = ["# Examples"]
    for example_dir in example_dirs:
        example_name = example_dir.name
        header_name = example_name.replace("_", " ").replace("-", " ").title()
        main_path = example_dir / "main.tf"
        assert main_path.exists(), f"{main_path} does not exist, every example must have a main.tf"
        content.extend(
            [
                f"## [{header_name}](./examples/{example_name})",
                "",
                "```terraform",
                main_path.read_text(),
                "```",
                "",
                "",
            ]
        )
    return "\n".join(content)


_static_terraform_config = """\
formatter: markdown document
output:
  file: "FILENAME"
  mode: inject
  template: |-
    START_MARKER
    {{ .Content }}
    END_MARKER
sort:
  enabled: true
  by: required
"""


def terraform_docs_config_content(module: ModuleGenConfig) -> str:
    config = _static_terraform_config
    for replacement_in, replacement_out in [
        ("FILENAME", module.readme_path().name),
        ("START_MARKER", ReadmeMarkers.as_start(ReadmeMarkers.TF_DOCS)),
        ("END_MARKER", ReadmeMarkers.as_end(ReadmeMarkers.TF_DOCS)),
    ]:
        config = config.replace(replacement_in, replacement_out)
    return config


def generate_readme(module: ModuleGenConfig) -> str:
    readme_path = module.readme_path()
    assert readme_path.exists(), (
        f"{readme_path} does not exist, currently a boilerplate is expected, consider adding to {readme_path}\n{ReadmeMarkers.example_boilerplate()}"
    )
    update_between_markers(
        readme_path,
        _readme_disclaimer,
        ReadmeMarkers.as_start(ReadmeMarkers.DISCLAIMER),
        ReadmeMarkers.as_end(ReadmeMarkers.DISCLAIMER),
    )
    examples_path = module.examples_path
    if minimal_tfvars := module.minimal_tfvars:
        example_name = module.example_name("minimal", 1)
        example_dir_path = examples_path / example_name
        main_tf = example_main_tf(module, minimal_tfvars)
        ensure_parents_write_text(example_dir_path / "main.tf", main_tf)
    run_and_wait("terraform fmt -recursive .", cwd=module.module_path, allow_non_zero_exit=True, ansi_content=False)
    example_section = read_examples(module)
    update_between_markers(
        readme_path,
        example_section,
        ReadmeMarkers.as_start(ReadmeMarkers.EXAMPLE),
        ReadmeMarkers.as_end(ReadmeMarkers.EXAMPLE),
    )
    docs_config_path = module.terraform_docs_config_path()
    if docs_config_path.exists():
        logger.warning(f"{docs_config_path} already exists, skipping generation")
    else:
        config_content = terraform_docs_config_content(module)
        ensure_parents_write_text(docs_config_path, config_content)
        logger.info(f"generated {docs_config_path}")
    run_and_wait(f"terraform-docs -c {docs_config_path} .", cwd=module.module_path)
    if module.post_readme_processor:
        readme_content = module.post_readme_processor(readme_path.read_text())
        ensure_parents_write_text(readme_path, readme_content)
    return readme_path.read_text()
