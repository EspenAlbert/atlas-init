import logging
from collections import defaultdict
from functools import total_ordering
from pathlib import Path

import typer
from model_lib import Entity, Event, dump, parse_payload
from pydantic import Field

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.cli_tf.hcl.modifier import (
    BLOCK_TYPE_OUTPUT,
    BLOCK_TYPE_VARIABLE,
    update_descriptions,
)

logger = logging.getLogger(__name__)


class UpdateExamples(Entity):
    examples_base_dir: Path
    var_descriptions: dict[str, str]
    output_descriptions: dict[str, str] = Field(default_factory=dict)
    skip_tf_fmt: bool = False


@total_ordering
class TFConfigDescriptionChange(Event):
    path: Path
    name: str
    before: str
    after: str
    block_type: str

    @property
    def changed(self) -> bool:
        return self.after not in ("", self.before)

    def __lt__(self, other) -> bool:
        if not isinstance(other, TFConfigDescriptionChange):
            raise TypeError
        return (self.path, self.name) < (other.path, other.name)


class UpdateExamplesOutput(Entity):
    before_var_descriptions: dict[str, str] = Field(default_factory=dict)
    before_output_descriptions: dict[str, str] = Field(default_factory=dict)
    changes: list[TFConfigDescriptionChange] = Field(default_factory=list)


def update_examples(event_in: UpdateExamples) -> UpdateExamplesOutput:
    changes = []
    existing_var_descriptions = update_block_descriptions(
        event_in.examples_base_dir,
        changes,
        event_in.var_descriptions,
        BLOCK_TYPE_VARIABLE,
    )
    existing_output_descriptions = update_block_descriptions(
        event_in.examples_base_dir,
        changes,
        event_in.output_descriptions,
        BLOCK_TYPE_OUTPUT,
    )
    if event_in.skip_tf_fmt:
        logger.info("skipping terraform fmt")
    else:
        assert run_binary_command_is_ok("terraform", "fmt -recursive", cwd=event_in.examples_base_dir, logger=logger), (
            "terraform fmt failed"
        )
    return UpdateExamplesOutput(
        before_var_descriptions=flatten_descriptions(existing_var_descriptions),
        before_output_descriptions=flatten_descriptions(existing_output_descriptions),
        changes=sorted(changes),
    )


def flatten_descriptions(descriptions: dict[str, list[str]]) -> dict[str, str]:
    return {
        key: "\n".join(desc for desc in sorted(set(descriptions)) if desc != "")
        for key, descriptions in descriptions.items()
    }


def update_block_descriptions(
    base_dir: Path,
    changes: list[TFConfigDescriptionChange],
    new_names: dict[str, str],
    block_type: str,
):
    all_existing_descriptions = defaultdict(list)
    in_files = sorted(base_dir.rglob("*.tf"))
    for tf_file in in_files:
        logger.info(f"looking for {block_type} in {tf_file}")
        new_tf, existing_descriptions = update_descriptions(tf_file, new_names, block_type=block_type)
        if not existing_descriptions:  # probably no variables in the file
            continue
        for name, descriptions in existing_descriptions.items():
            changes.extend(
                TFConfigDescriptionChange(
                    path=tf_file,
                    name=name,
                    before=description,
                    after=new_names.get(name, ""),
                    block_type=block_type,
                )
                for description in descriptions
            )
            all_existing_descriptions[name].extend(descriptions)
        if tf_file.read_text() == new_tf:
            logger.debug(f"no {block_type} changes for {tf_file}")
            continue
        tf_file.write_text(new_tf)
    return all_existing_descriptions


def update_example_cmd(
    examples_base_dir: Path = typer.Argument(
        ..., help="Directory containing *.tf files (can have many subdirectories)"
    ),
    var_descriptions: Path = typer.Option("", "--vars", help="Path to a JSON/yaml file with variable descriptions"),
    output_descriptions: Path = typer.Option("", "--outputs", help="Path to a JSON/yaml file with output descriptions"),
    skip_log_existing: bool = typer.Option(False, help="Log existing descriptions"),
    skip_log_changes: bool = typer.Option(False, help="Log variable updates"),
):
    var_descriptions_dict = parse_payload(var_descriptions) if var_descriptions else {}
    output_descriptions_dict = parse_payload(output_descriptions) if output_descriptions else {}
    event = UpdateExamples(
        examples_base_dir=examples_base_dir,
        var_descriptions=var_descriptions_dict,  # type: ignore
        output_descriptions=output_descriptions_dict,  # type: ignore
    )
    output = update_examples(event)
    if not skip_log_changes:
        for change in output.changes:
            if change.changed:
                logger.info(f"{change.path}({change.block_type}) {change.name}: {change.before} -> {change.after}")
    if not skip_log_existing:
        existing_var_yaml = dump(output.before_var_descriptions, "yaml")
        logger.info(f"Existing Variables:\n{existing_var_yaml}")
        existing_output_yaml = dump(output.before_output_descriptions, "yaml")
        logger.info(f"Existing Outputs:\n{existing_output_yaml}")
