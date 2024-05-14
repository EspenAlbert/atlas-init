import logging
from pathlib import Path
from typing import Literal

import pydantic
from model_lib import Entity, dump, field_names, parse_model
import requests

logger = logging.getLogger(__name__)


class ProviderSpecMapAttribute(Entity):
    computed_optional_required: Literal["computed_optional"]
    element_type: dict[str, dict]
    description: str


class ProviderSpecAttribute(Entity):
    name: str
    map: ProviderSpecMapAttribute | None = None

    def dump_provider_code_spec(self) -> dict:
        return self.model_dump(exclude_none=True)


class TFResource(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    name: str
    provider_spec_attributes: list[ProviderSpecAttribute]

    def dump_generator_config(self) -> dict:
        names = field_names(self)
        return self.model_dump(exclude=set(names))


class PyTerraformSchema(Entity):
    resources: list[TFResource]

    def resource(self, resource: str) -> TFResource:
        return next(r for r in self.resources if r.name == resource)


def parse_py_terraform_schema(path: Path) -> PyTerraformSchema:
    return parse_model(path, PyTerraformSchema)


def dump_generator_config(schema: PyTerraformSchema) -> str:
    resources = {}
    for resource in schema.resources:
        resources[resource.name] = resource.dump_generator_config()
    generator_config = {
        "provider": dict(name="mongodbatlas"),
        "resources": resources,
    }
    return dump(generator_config, "yaml")


class ProviderCodeSpec(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    provider: dict
    resources: list[dict]
    version: str

    def resource_attributes(self, name: str) -> list:
        for r in self.resources:
            if r["name"] == name:
                return r["schema"]["attributes"]
        raise ValueError(f"resource: {name} not found!")

    def resource_attribute_names(self, name: str) -> list[str]:
        return [a["name"] for a in self.resource_attributes(name)]


def update_provider_code_spec(
    schema: PyTerraformSchema, provider_code_spec_path: Path
) -> str:
    spec = parse_model(provider_code_spec_path, t=ProviderCodeSpec)
    for resource in schema.resources:
        resource_name = resource.name
        if extra_spec_attributes := resource.provider_spec_attributes:
            resource_attributes = spec.resource_attributes(resource_name)
            existing_names = spec.resource_attribute_names(resource_name)
            new_names = [extra.name for extra in extra_spec_attributes]
            if both := set(existing_names) & set(new_names):
                raise ValueError(
                    f"resource: {resource_name}, has already: {both} attributes"
                )
            resource_attributes.extend(
                extra.dump_provider_code_spec() for extra in extra_spec_attributes
            )
    return dump(spec, "json")


# reusing url from terraform-provider-mongodbatlas/scripts/schema-scaffold.sh
ADMIN_API_URL = "https://raw.githubusercontent.com/mongodb/atlas-sdk-go/main/openapi/atlas-api-transformed.yaml"


def download_admin_api(dest: Path) -> None:
    logger.info(f"downloading admin api to {dest} from {ADMIN_API_URL}")
    response = requests.get(ADMIN_API_URL)
    response.raise_for_status()
    dest.write_bytes(response.content)
