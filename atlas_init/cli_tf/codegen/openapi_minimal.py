from queue import Queue
from atlas_init.cli_tf.codegen.models import ResourceConfig
from atlas_init.cli_tf.openapi import OpenapiSchema
from atlas_init.cli_tf.schema_v2 import SchemaResource


def minimal_api_spec_simplified(resource: ResourceConfig, full_spec: OpenapiSchema) -> OpenapiSchema:
    minimal_spec = OpenapiSchema(
        openapi=full_spec.openapi,
        info={"description": "minimal spec", "version": full_spec.info["version"], "title": full_spec.info["title"]},
        paths={},
        components={"schemas": {}, "parameters": {}},
    )
    include_refs: Queue[str] = Queue()
    seen_refs: set[str] = set()

    for path in resource.paths:
        path_dict = minimal_spec.paths[path] = full_spec.paths[path]
        remove_non_2xx_responses(path_dict)
        for ref in full_spec.method_refs(path):
            minimal_spec.add_schema_ref(ref, full_spec.resolve_ref(ref))
            include_refs.put(ref)
        for ref in full_spec.parameter_refs(path):
            minimal_spec.add_schema_ref(ref, full_spec.resolve_ref(ref))
            include_refs.put(ref)

    def add_from_resource_ref(ref_resource: SchemaResource) -> None:
        for attribute in ref_resource.attributes.values():
            if attribute.schema_ref:
                minimal_spec.add_schema_ref(attribute.schema_ref, full_spec.resolve_ref(attribute.schema_ref))
                include_refs.put(attribute.schema_ref)
            if attribute.parameter_ref:
                minimal_spec.add_schema_ref(
                    attribute.parameter_ref,
                    full_spec.resolve_ref(attribute.parameter_ref),
                )
            if ref := attribute.additional_properties_ref:
                minimal_spec.add_schema_ref(ref, full_spec.resolve_ref(ref))
                include_refs.put(ref)
        for ref in ref_resource.extra_refs():
            minimal_spec.add_schema_ref(ref, full_spec.resolve_ref(ref))
            include_refs.put(ref)

    while not include_refs.empty():
        ref = include_refs.get()
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        if ref.startswith(full_spec.SCHEMAS_PREFIX):
            ref_resource = full_spec.schema_ref_component(ref, set())
            add_from_resource_ref(ref_resource)
        else:
            param_name = ref.split("/")[-1]
            minimal_spec.components["parameters"][param_name] = full_spec.resolve_ref(ref)
    sorted_components = sorted(minimal_spec.components["schemas"].items())
    sorted_parameters = sorted(minimal_spec.components["parameters"].items())
    modify_schema_properties(sorted_components)
    minimal_spec.components["schemas"] = dict(sorted_components)
    minimal_spec.components["parameters"] = dict(sorted_parameters)
    return minimal_spec


def modify_schema_properties(schema_properties: list[tuple[str, dict]]):
    for _, schema_values in schema_properties:
        properties = schema_values.get("properties", {})
        for _, prop_values in properties.items():
            prop_values.pop("name", None)  # Remove 'name' field if it exists


def remove_non_2xx_responses(path_dict: dict) -> None:
    for method_dict in path_dict.values():
        method_dict["responses"] = {
            code: response for code, response in method_dict.get("responses", {}).items() if code.startswith("2")
        }
