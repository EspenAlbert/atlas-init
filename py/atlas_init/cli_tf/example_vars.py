import logging
from collections import defaultdict
from functools import total_ordering
from pathlib import Path

from model_lib import Entity, Event
from pydantic import Field

from atlas_init.cli_tf.hcl.modifier import update_descriptions

logger = logging.getLogger(__name__)


class UpdateExampleVars(Entity):
    examples_base_dir: Path
    var_descriptions: dict[str, str]


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
    in_files = list(event_in.examples_base_dir.rglob("*.tf"))
    for tf_file in in_files:
        new_tf, existing_descriptions = update_descriptions(tf_file, event_in.var_descriptions)
        if not existing_descriptions:
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
            logger.warning(f"no changes for {tf_file}")
            continue
        tf_file.write_text(new_tf)
    return UpdateExampleVarsOutput(
        before_descriptions={
            key: "\n".join(desc for desc in descriptions if desc != "")
            for key, descriptions in all_existing_descriptions.items()
        },
        changes=sorted(changes),
    )
