from __future__ import annotations
import logging
from enum import StrEnum
from pathlib import Path
from typing import Callable, TypeAlias

from ask_shell import run_and_wait
from zero_3rdparty.file_utils import ensure_parents_write_text, update_between_markers

from atlas_init.tf_ext.gen_examples import read_example_dirs
from atlas_init.tf_ext.models_module import EXAMPLES_DIRNAME, README_FILENAME, TERRAFORM_DOCS_CONFIG_FILENAME

logger = logging.getLogger(__name__)
_readme_disclaimer = """\
## Disclaimer
This Module is not meant for external consumption.
It is part of a development PoC.
Any usage problems will not be supported.
However, if you have any ideas or feedback, feel free to open a Github Issue!
"""


class ReadmeMarkers(StrEnum):
    DISCLAIMER = "DISCLAIMER"
    MODULES = "MODULES"
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

    @classmethod
    def readme_generators(cls) -> ReadmeGenerators:
        return [
            (cls.DISCLAIMER, lambda _: _readme_disclaimer),
            (cls.EXAMPLE, lambda workspace: read_examples(workspace / EXAMPLES_DIRNAME)),
        ]


ReadmeGenerators: TypeAlias = list[tuple[ReadmeMarkers, Callable[[Path], str]]]


def read_examples(examples_dir: Path) -> str:
    example_dirs = read_example_dirs(examples_dir)
    if not example_dirs:
        return ""
    # ensure the examples are formatted first
    run_and_wait("terraform fmt -recursive .", cwd=examples_dir.parent, allow_non_zero_exit=True, ansi_content=False)
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


def terraform_docs_config_content(readme_path: Path) -> str:
    config = _static_terraform_config
    for replacement_in, replacement_out in [
        ("FILENAME", readme_path.name),
        ("START_MARKER", ReadmeMarkers.as_start(ReadmeMarkers.TF_DOCS)),
        ("END_MARKER", ReadmeMarkers.as_end(ReadmeMarkers.TF_DOCS)),
    ]:
        config = config.replace(replacement_in, replacement_out)
    return config


def generate_and_write_readme(terraform_workdir: Path, *, generators: ReadmeGenerators | None = None) -> str:
    generators = generators or ReadmeMarkers.readme_generators()
    readme_path = terraform_workdir / README_FILENAME
    assert readme_path.exists(), (
        f"{readme_path} does not exist, currently a boilerplate is expected, consider adding to {readme_path}\n{ReadmeMarkers.example_boilerplate()}"
    )
    for marker, generator in generators:
        content = generator(terraform_workdir)
        if not content:
            continue
        update_between_markers(
            readme_path,
            content,
            ReadmeMarkers.as_start(marker),
            ReadmeMarkers.as_end(marker),
        )
    generate_terraform_docs(readme_path)
    logger.info(f"updated {readme_path}")
    return readme_path.read_text()


def generate_terraform_docs(readme_path: Path) -> None:
    docs_config_path = readme_path.parent / TERRAFORM_DOCS_CONFIG_FILENAME
    if docs_config_path.exists():
        logger.warning(f"{docs_config_path} already exists, skipping generation")
    else:
        config_content = terraform_docs_config_content(readme_path)
        ensure_parents_write_text(docs_config_path, config_content)
        logger.info(f"generated {docs_config_path}")
    run_and_wait(f"terraform-docs -c {docs_config_path} .", cwd=readme_path.parent)
    readme_content = _default_link_updater(readme_path.read_text())
    ensure_parents_write_text(readme_path, readme_content)


def _default_link_updater(readme_content: str) -> str:  # can be a global replacer for now
    for replace_in, replace_out in {
        "docs/resources/advanced_cluster": r"docs/resources/advanced_cluster%2520%2528preview%2520provider%25202.0.0%2529"
    }.items():
        readme_content = readme_content.replace(replace_in, replace_out)
    return readme_content
