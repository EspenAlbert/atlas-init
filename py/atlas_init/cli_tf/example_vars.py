import logging
from collections import defaultdict
from functools import total_ordering
from pathlib import Path

import typer
from model_lib import Entity, Event, dump, parse_payload
from pydantic import Field

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.cli_tf.hcl.modifier import update_descriptions

logger = logging.getLogger(__name__)


class UpdateExampleVars(Entity):
    examples_base_dir: Path
    var_descriptions: dict[str, str]
    skip_tf_fmt: bool = False


@total_ordering
class VarDescriptionChange(Event):
    path: Path
    name: str
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.after not in ("", self.before)

    def __lt__(self, other) -> bool:
        if not isinstance(other, VarDescriptionChange):
            raise TypeError
        return (self.path, self.name) < (other.path, other.name)


class UpdateExampleVarsOutput(Entity):
    before_descriptions: dict[str, str] = Field(default_factory=dict)
    changes: list[VarDescriptionChange] = Field(default_factory=list)


def update_example_vars(event_in: UpdateExampleVars) -> UpdateExampleVarsOutput:
    changes = []
    all_existing_descriptions = defaultdict(list)
    in_files = sorted(event_in.examples_base_dir.rglob("*.tf"))
    for tf_file in in_files:
        logger.info(f"looking for vars in {tf_file}")
        new_tf, existing_descriptions = update_descriptions(tf_file, event_in.var_descriptions)
        if not existing_descriptions:  # probably no variables in the file
            continue
        for name, descriptions in existing_descriptions.items():
            changes.extend(
                VarDescriptionChange(
                    path=tf_file,
                    name=name,
                    before=description,
                    after=event_in.var_descriptions.get(name, ""),
                )
                for description in descriptions
            )
            all_existing_descriptions[name].extend(descriptions)
        if tf_file.read_text() == new_tf:
            logger.debug(f"no changes for {tf_file}")
            continue
        tf_file.write_text(new_tf)
    if event_in.skip_tf_fmt:
        logger.info("skipping terraform fmt")
    else:
        assert run_binary_command_is_ok(
            "terraform", "fmt -recursive", cwd=event_in.examples_base_dir, logger=logger
        ), "terraform fmt failed"
    return UpdateExampleVarsOutput(
        before_descriptions={
            key: "\n".join(desc for desc in sorted(set(descriptions)) if desc != "")
            for key, descriptions in all_existing_descriptions.items()
        },
        changes=sorted(changes),
    )


def update_example_vars_cmd(
    examples_base_dir: Path = typer.Argument(
        ..., help="Directory containing *.tf files (can have many subdirectories)"
    ),
    var_descriptions: Path = typer.Argument(..., help="Path to a JSON/yaml file with variable descriptions"),
    skip_log_existing: bool = typer.Option(False, help="Log existing descriptions"),
    skip_log_changes: bool = typer.Option(False, help="Log variable updates"),
):
    variable_descriptions = parse_payload(var_descriptions)
    event = UpdateExampleVars(
        examples_base_dir=examples_base_dir,
        var_descriptions=variable_descriptions,  # type: ignore
    )
    output = update_example_vars(event)
    if not skip_log_changes:
        for change in output.changes:
            if change.changed:
                logger.info(f"{change.path} {change.name}: {change.before} -> {change.after}")
    if not skip_log_existing:
        existing_yaml = dump(output.before_descriptions, "yaml")
        logger.info(f"Existing Variables:\n{existing_yaml}")
