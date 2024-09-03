import logging
from collections.abc import Iterable
from pathlib import Path
from queue import Queue
from typing import ClassVar

from model_lib import Entity
from pydantic import Field

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
    PARAMETERS_PREFIX: ClassVar[str] = "#/components/parameters/"
    SCHEMAS_PREFIX: ClassVar[str] = "#/components/schemas/"

    openapi: str
    info: dict
    paths: dict
    components: dict
    tags: list = Field(default_factory=list)

    def create_method(self, path: str) -> dict | None:
        return self.paths.get(path, {}).get("post")

    def read_method(self, path: str) -> dict | None:
        return self.paths.get(path, {}).get("get")

    def method_refs(self, path: str) -> Iterable[str]:
        for method in [self.create_method(path), self.read_method(path)]:
            if method:
                if req_ref := self.method_request_body_ref(method):
                    yield req_ref
                if resp_ref := self.method_response_ref(method):
                    yield resp_ref

    def parameter(self, ref: str) -> dict:
        assert ref.startswith(OpenapiSchema.PARAMETERS_PREFIX)
        parameter_name = ref.split("/")[-1]
        param_dict = self.components["parameters"][parameter_name]
        assert isinstance(param_dict, dict), f"Expected a dict @ {ref}"
        return param_dict

    def schema_properties(self, ref: str) -> Iterable[dict]:
        assert ref.startswith(OpenapiSchema.SCHEMAS_PREFIX)
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
        content = {**response.get("content", {})}  # avoid side effects
        if not content:
            return None
        key, value = content.popitem()
        if not isinstance(key, str) or not key.endswith("json"):
            return None
        return value.get("schema", {}).get("$ref")

    def schema_ref_component(self, ref: str, attributes_skip: set[str]) -> SchemaResource:
        schemas = self.components.get("schemas", {})
        assert isinstance(schemas, dict), "Expected a dict @ components.schemas"
        schema = schemas.get(ref.split("/")[-1])
        assert isinstance(schema, dict), f"Expected a dict @ components.schemas.{ref}"
        return self._as_schema_resource(attributes_skip, schema, ref)

    def schema_ref_components(self, attributes_skip: set[str]) -> Iterable[SchemaResource]:
        schemas = self.components.get("schemas", {})
        assert isinstance(schemas, dict), "Expected a dict @ components.schemas"
        for name, schema in schemas.items():
            ref = f"#/components/schemas/{name}"
            yield self._as_schema_resource(attributes_skip, schema, ref)

    def _as_schema_resource(self, attributes_skip: set[str], schema: dict, ref: str):
        schema_resource = SchemaResource(
            name=ref,
            description=schema.get("description", ""),
            attributes_skip=attributes_skip,
        )
        required_names = schema.get("required", [])
        for prop in self.schema_properties(ref):
            if attr := parse_api_spec_param(self, prop, schema_resource):
                attr.is_required = prop["name"] in required_names
                schema_resource.attributes[attr.name] = attr
        return schema_resource

    def add_schema_ref(self, ref: str, ref_value: dict) -> None:
        if ref.startswith(self.PARAMETERS_PREFIX):
            prefix = self.PARAMETERS_PREFIX
            parent_dict = self.components["parameters"]
        elif ref.startswith(self.SCHEMAS_PREFIX):
            prefix = self.SCHEMAS_PREFIX
            parent_dict = self.components["schemas"]
        else:
            err_msg = f"Unknown schema_ref {ref}"
            raise ValueError(err_msg)
        parent_dict[ref.removeprefix(prefix)] = ref_value

    def resolve_ref(self, ref: str) -> dict:
        if ref.startswith(self.PARAMETERS_PREFIX):
            return self.parameter(ref)
        if ref.startswith(self.SCHEMAS_PREFIX):
            return self.components["schemas"][ref.split("/")[-1]]
        err_msg = f"Unknown ref {ref}"
        raise ValueError(err_msg)


def parse_api_spec_param(api_spec: OpenapiSchema, param: dict, resource: SchemaResource) -> SchemaAttribute | None:
    match param:
        case {"$ref": ref} if ref.startswith(OpenapiSchema.PARAMETERS_PREFIX):
            param_root = api_spec.parameter(ref)
            found_attribute = parse_api_spec_param(api_spec, param_root, resource)
            if found_attribute:
                found_attribute.parameter_ref = ref
            return found_attribute
        case {"$ref": ref, "name": name} if ref.startswith(OpenapiSchema.SCHEMAS_PREFIX):
            # nested attribute
            attribute = SchemaAttribute(
                type="object",
                name=name,
                schema_ref=ref,
            )
        case {"type": "array", "items": {"$ref": ref}, "name": name}:
            attribute = SchemaAttribute(
                type="array",
                name=name,
                schema_ref=ref,
                description=param.get("description", ""),
                is_computed=param.get("readOnly", False),
                is_required=param.get("required", False),
            )
        case {"name": name, "schema": schema}:
            attribute = SchemaAttribute(
                type=schema["type"],
                name=name,
                description=param.get("description", ""),
                is_computed=schema.get("readOnly", False),
                is_required=param.get("required", False),
            )
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
        logger.info(f"Merging attribute {attribute.name} into {existing.name}")
        attribute = existing.merge(attribute)
    except NewAttribute:
        logger.info("Adding new attribute %s to %s", attribute.name, resource.name)
    except SkipAttribute:
        return None
    resource.attributes[attribute.name] = attribute
    return attribute


def add_api_spec_info(schema: SchemaV2, api_spec_path: Path, *, minimal_refs: bool = False) -> None:
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
                    parse_api_spec_param(api_spec, property_dict, resource)
        for path in resource.paths:
            read_method = api_spec.read_method(path)
            if not read_method:
                continue
            for param in read_method.get("parameters", []):
                parse_api_spec_param(api_spec, param, resource)
            if response_ref := api_spec.method_response_ref(read_method):
                for property_dict in api_spec.schema_properties(response_ref):
                    parse_api_spec_param(api_spec, property_dict, resource)
    if minimal_refs:
        minimal_ref_resources(schema, api_spec)
    else:
        for resource in api_spec.schema_ref_components(schema.attributes_skip):
            schema.ref_resources[resource.name] = resource


def minimal_ref_resources(schema: SchemaV2, api_spec: OpenapiSchema) -> None:
    include_refs = Queue()
    seen_refs = set()
    for resource in schema.resources.values():
        for attribute in resource.attributes.values():
            if attribute.schema_ref:
                include_refs.put(attribute.schema_ref)
    while not include_refs.empty():
        ref = include_refs.get()
        logger.info(f"Adding ref {ref}")
        seen_refs.add(ref)
        ref_resource = api_spec.schema_ref_component(ref, schema.attributes_skip)
        schema.ref_resources[ref_resource.name] = ref_resource
        for attribute in ref_resource.attributes.values():
            if attribute.schema_ref and attribute.schema_ref not in seen_refs:
                include_refs.put(attribute.schema_ref)


def minimal_api_spec(schema: SchemaV2, original_api_spec_path: Path) -> OpenapiSchema:
    schema.reset_attributes_skip()
    full_spec = parse_model(original_api_spec_path, t=OpenapiSchema)
    add_api_spec_info(schema, original_api_spec_path, minimal_refs=True)
    minimal_spec = OpenapiSchema(
        openapi=full_spec.openapi,
        info=full_spec.info,
        paths={},
        components={"schemas": {}, "parameters": {}},
    )
    include_refs = Queue()
    seen_refs = set()

    def add_from_resource(resource: SchemaResource) -> None:
        for path in resource.paths:
            minimal_spec.paths[path] = full_spec.paths[path]
            for ref in full_spec.method_refs(path):
                minimal_spec.add_schema_ref(ref, full_spec.resolve_ref(ref))
                include_refs.put(ref)
        for attribute in resource.attributes.values():
            if attribute.schema_ref:
                minimal_spec.add_schema_ref(attribute.schema_ref, full_spec.resolve_ref(attribute.schema_ref))
                include_refs.put(attribute.schema_ref)
            if attribute.parameter_ref:
                minimal_spec.add_schema_ref(
                    attribute.parameter_ref,
                    full_spec.resolve_ref(attribute.parameter_ref),
                )

    for resource in schema.resources.values():
        add_from_resource(resource)
    while not include_refs.empty():
        ref = include_refs.get()
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        ref_resource = full_spec.schema_ref_component(ref, schema.attributes_skip)
        add_from_resource(ref_resource)
    return minimal_spec
