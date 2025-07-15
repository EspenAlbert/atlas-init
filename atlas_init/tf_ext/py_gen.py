from dataclasses import Field
from typing import List, Union, get_args, get_origin

primitive_types = (str, float, bool, int)


def as_set(values: list[str]) -> str:
    return f"{{{', '.join(repr(v) for v in values)}}}" if values else "set()"


def make_post_init_line(field_name: str, elem_type: str, is_map: bool = False, is_list: bool = False) -> str:
    if is_map:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = {{k: {elem_type}(**v) if not isinstance(v, {elem_type}) else v for k, v in self.{field_name}.items()}}"
        )
    elif is_list:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = [{elem_type}(**x) if not isinstance(x, {elem_type}) else x for x in self.{field_name}]"
        )
    else:
        return (
            f"        if self.{field_name} is not None and not isinstance(self.{field_name}, {elem_type}):\n"
            f"            self.{field_name} = {elem_type}(**self.{field_name})"
        )


def make_post_init_line_from_field(field: Field) -> str:
    field_type = field.type
    origin = get_origin(field_type)
    args = get_args(field_type)

    if origin is Union and type(None) in args:
        non_none_args = [arg for arg in args if arg is not type(None)]
        assert len(non_none_args) == 1, f"Expected one non-None type in Union, got {non_none_args}"
        inner_type = non_none_args[0]
        if inner_type in primitive_types:
            return ""

        # Handle Optional[List[X]]
        inner_origin = get_origin(inner_type)
        inner_args = get_args(inner_type)
        if inner_origin in (list, List) and inner_args:
            item_type = inner_args[0]
            if item_type in primitive_types:
                return ""
            return make_post_init_line(field.name, item_type.__name__, is_list=True)
        return make_post_init_line(field.name, getattr(inner_type, "__name__", str(inner_type)))
    return ""
