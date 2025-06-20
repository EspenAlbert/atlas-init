from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from enum import Enum


class HttpMethod(str, Enum):
    """HTTP methods enum"""

    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    DELETE = "DELETE"
    PUT = "PUT"


class WaitConfig(BaseModel):
    """Configuration for waiting/polling operations"""

    state_property: str = Field(..., description="Property to check for state")
    pending_states: List[str] = Field(..., description="States that indicate operation is still in progress")
    target_states: List[str] = Field(..., description="States that indicate operation is complete")
    timeout_seconds: int = Field(..., description="Maximum time to wait in seconds")
    min_timeout_seconds: int = Field(..., description="Minimum timeout in seconds")
    delay_seconds: int = Field(..., description="Delay between polling attempts in seconds")


class OperationConfig(BaseModel):
    """Configuration for a single API operation (read, create, update, delete)"""

    path: str = Field(..., description="API endpoint path with path parameters")
    method: HttpMethod = Field(..., description="HTTP method for the operation")
    wait: Optional[WaitConfig] = Field(None, description="Wait configuration for async operations")


class SchemaOverrides(BaseModel):
    """Schema overrides for specific fields"""

    sensitive: Optional[bool] = Field(None, description="Mark field as sensitive")
    # Add other override properties as needed


class SchemaConfig(BaseModel):
    """Schema configuration for the resource"""

    aliases: Optional[Dict[str, str]] = Field(None, description="Field name aliases mapping")
    overrides: Optional[Dict[str, SchemaOverrides]] = Field(None, description="Field-specific overrides")
    ignores: Optional[List[str]] = Field(None, description="Fields to ignore")
    timeouts: Optional[List[str]] = Field(None, description="Operations that support timeouts")


class ResourceConfig(BaseModel):
    """Configuration for a single API resource"""

    read: Optional[OperationConfig] = Field(None, description="Read operation configuration")
    create: Optional[OperationConfig] = Field(None, description="Create operation configuration")
    update: Optional[OperationConfig] = Field(None, description="Update operation configuration")
    delete: Optional[OperationConfig] = Field(None, description="Delete operation configuration")
    version_header: Optional[str] = Field(None, description="API version header value")
    custom_schema: Optional[SchemaConfig] = Field(None, description="Schema configuration", alias="schema")

    @property
    def paths(self) -> list[str]:
        return [
            operation.path
            for operation in [self.read, self.create, self.update, self.delete]
            if operation and operation.path
        ]


class ApiResourcesConfig(BaseModel):
    """Root configuration model containing all API resources"""

    resources: Dict[str, ResourceConfig] = Field(..., description="Dictionary of resource configurations")

    class Config:
        extra = "allow"  # Allow additional fields not explicitly defined

    def get_resource(self, name: str) -> ResourceConfig:
        """Get a specific resource configuration by name"""
        resource = self.resources.get(name)
        if not resource:
            raise ValueError(f"Resource '{name}' not found in configuration")
        return resource

    def list_resources(self) -> List[str]:
        """Get list of all resource names"""
        return list(self.resources.keys())

    def get_resources_with_operation(self, operation: str) -> List[str]:
        """Get list of resources that support a specific operation"""
        result = []
        result.extend(
            name
            for name, config in self.resources.items()
            if hasattr(config, operation) and getattr(config, operation) is not None
        )
        return result
