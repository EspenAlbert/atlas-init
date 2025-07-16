from typing import Optional
from dataclasses import dataclass


@dataclass
class _Nested:
    name: str
    age: int


@dataclass
class _MyCls:
    string: str
    number: int
    floating_point: float
    boolean: bool
    flat_list: list[str]
    flat_dict: dict[str, str]
    nested_dict: dict[str, _Nested]
    nested_list: list[_Nested]
    optional_nested: Optional[_Nested]
    required_nested: _Nested
    optional_string: Optional[str] = None
    optional_number: Optional[int] = None
    optional_floating_point: Optional[float] = None
    optional_boolean: Optional[bool] = None
    optional_flat_list: Optional[list[str]] = None
    optional_flat_dict: Optional[dict[str, str]] = None
    optional_nested_dict: Optional[dict[str, _Nested]] = None
    optional_nested_list: Optional[list[_Nested]] = None

    def __post_init__(self):
        assert isinstance(self.nested_dict, dict), f"Expected nested_dict to be a dict, got {type(self.nested_dict)}"
        self.nested_dict = {k: v if isinstance(v, _Nested) else _Nested(**v) for k, v in self.nested_dict.items()}
        assert isinstance(self.nested_list, list), f"Expected nested_list to be a list, got {type(self.nested_list)}"
        self.nested_list = [x if isinstance(x, _Nested) else _Nested(**x) for x in self.nested_list]
        if self.optional_nested is not None and not isinstance(self.optional_nested, _Nested):
            assert isinstance(self.optional_nested, dict), (
                f"Expected optional_nested to be a _Nested or a dict, got {type(self.optional_nested)}"
            )
            self.optional_nested = _Nested(**self.optional_nested)
        if not isinstance(self.required_nested, _Nested):
            assert isinstance(self.required_nested, dict), (
                f"Expected required_nested to be a _Nested or a dict, got {type(self.required_nested)}"
            )
            self.required_nested = _Nested(**self.required_nested)
        if self.optional_nested_dict is not None:
            self.optional_nested_dict = {
                k: v if isinstance(v, _Nested) else _Nested(**v) for k, v in self.optional_nested_dict.items()
            }
        if self.optional_nested_list is not None:
            self.optional_nested_list = [
                x if isinstance(x, _Nested) else _Nested(**x) for x in self.optional_nested_list
            ]
