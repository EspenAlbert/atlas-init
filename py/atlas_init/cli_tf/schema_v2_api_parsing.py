import logging
from collections.abc import Iterable
from pathlib import Path

from model_lib import Entity

from atlas_init.cli_tf.schema_v2 import (
    NewAttribute,
    SchemaAttribute,
    SchemaResource,
    SchemaV2,
    SkipAttribute,
    parse_model,
)

logger = logging.getLogger(__name__)


class OpenapiSchema(Entity):
    openapi: str
    info: dict
    paths: dict
    components: dict
    tags: list

    def create_method(self, path: str) -> dict | None:
        return self.paths.get(path, {}).get("post")

    def read_method(self, path: str) -> dict | None:
        return self.paths.get(path, {}).get("get")

    def parameter(self, ref: str) -> dict:
        assert ref.startswith("#/components/parameters/")
        parameter_name = ref.split("/")[-1]
        param_dict = self.components["parameters"][parameter_name]
        assert isinstance(param_dict, dict), f"Expected a dict @ {ref}"
        return param_dict

    def schema_properties(self, ref: str) -> Iterable[dict]:
        assert ref.startswith("#/components/schemas/")
        schema_name = ref.split("/")[-1]
        schema_dict = self.components["schemas"][schema_name]
        assert isinstance(schema_dict, dict), f"Expected a dict @ {ref}"
        properties = schema_dict.get("properties", {})
        assert isinstance(properties, dict), f"Expected a dict @ {ref}.properties"
        for name, prop in properties.items():
            assert isinstance(prop, dict), f"Expected a dict @ {ref}.properties.{name}"
            prop["name"] = name
            yield prop

    def method_request_body_ref(self, method: dict) -> str | None:
        request_body = method.get("requestBody", {})
        return self._unpack_schema_ref(request_body)

    def method_response_ref(self, method: dict) -> str | None:
        responses = method.get("responses", {})
        ok_response = responses.get("200", {})
        return self._unpack_schema_ref(ok_response)

    def _unpack_schema_ref(self, response: dict) -> str | None:
        content = response.get("content", {})
        if not content:
            return None
        key, value = content.popitem()
        if not isinstance(key, str) or not key.endswith("json"):
            return None
        return value.get("schema", {}).get("$ref")
    
    def schema_ref_components(self, attributes_skip: set[str]) -> Iterable[SchemaResource]:
        schemas = self.components.get("schemas", {})
        assert isinstance(schemas, dict), "Expected a dict @ components.schemas"
        for name, schema in schemas.items():
            ref = f"#/components/schemas/{name}"
            schema_resource = SchemaResource(name=ref, description=schema.get("description", ""), attributes_skip=attributes_skip)
            required_names = schema.get("required", [])
            for prop in self.schema_properties(ref):
                if attr := parse_api_spec_param(self, prop, schema_resource):
                    attr.is_required = prop["name"] in required_names
                    schema_resource.attributes[attr.name] = attr
            yield schema_resource


def parse_api_spec_param(
    api_spec: OpenapiSchema, param: dict, resource: SchemaResource, parent_ref: str = ""
) -> SchemaAttribute | None:
    match param:
        case {"$ref": ref} if ref.startswith("#/components/parameters/"):
            param_root = api_spec.parameter(ref)
            return parse_api_spec_param(api_spec, param_root, resource, parent_ref=ref)
        case {"$ref": ref, "name": name} if ref.startswith("#/components/schemas/"):
            # nested attribute
            attribute = SchemaAttribute(
                type="object",
                name=name,
                schema_ref=ref,
            )
        case {"name": name, "schema": schema}:
            attribute = SchemaAttribute(
                type=schema["type"],
                name=name,
                description=param.get("description", ""),
                is_computed=schema.get("readOnly", False),
                is_required=param.get("required", False),
            )  # type: ignore
        case {"name": name, "type": type_}:
            attribute = SchemaAttribute(
                type=type_,
                name=name,
                description=param.get("description", ""),
                is_computed=param.get("readOnly", False),
                is_required=param.get("required", False),
            )
        case _:
            raise NotImplementedError
    try:
        existing = resource.lookup_attribute(attribute.name)
        logger.info("Merging attribute %s into %s", attribute.name, resource.name)
        attribute = existing.merge(attribute)
    except NewAttribute:
        logger.info("Adding new attribute %s to %s", attribute.name, resource.name)
    except SkipAttribute:
        return None
    resource.attributes[attribute.name] = attribute
    return attribute


def add_api_spec_info(schema: SchemaV2, api_spec_path: Path) -> None:
    api_spec = parse_model(api_spec_path, t=OpenapiSchema)
    for resource in schema.resources.values():
        for path in resource.paths:
            create_method = api_spec.create_method(path)
            if not create_method:
                continue
            for param in create_method.get("parameters", []):
                parse_api_spec_param(api_spec, param, resource)
            if req_ref := api_spec.method_request_body_ref(create_method):
                for property_dict in api_spec.schema_properties(req_ref):
                    parse_api_spec_param(
                        api_spec, property_dict, resource, parent_ref=req_ref
                    )
        for path in resource.paths:
            read_method = api_spec.read_method(path)
            if not read_method:
                continue
            for param in read_method.get("parameters", []):
                parse_api_spec_param(api_spec, param, resource)
            if response_ref := api_spec.method_response_ref(read_method):
                for property_dict in api_spec.schema_properties(response_ref):
                    parse_api_spec_param(
                        api_spec, property_dict, resource, parent_ref=response_ref
                    )
    for resource in api_spec.schema_ref_components(schema.attributes_skip):
        schema.ref_resources[resource.name] = resource