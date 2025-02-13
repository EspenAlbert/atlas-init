from pathlib import Path

from model_lib import Entity, Event
from pydantic import Field


class UpdateExampleVars(Entity):
    examples_base_dir: Path
    var_descriptions: dict[str, str]

class DescriptionChange(Event):
    path: Path
    name: str
    before: str
    after: str


class UpdateExampleVarsOutput(Entity):
    updated_examples: list[DescriptionChange] = Field(default_factory=list)

def update_example_vars(input: UpdateExampleVars) -> UpdateExampleVarsOutput:
    for tf_file in input.examples_base_dir.rglob("*.tf"):
        pass
