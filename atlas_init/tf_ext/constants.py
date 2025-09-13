DEFAULT_EXTERNAL_SUBSTRINGS = ["aws", "azure", "google", "gcp"]
DEFAULT_INTERNAL_SUBSTRINGS = ["atlas", "mongo", "aws_region", "gcp_region", "azure_region", "cidr"]
ATLAS_PROVIDER_NAME = "mongodbatlas"


def provider_name(resource_type: str) -> str:
    return resource_type.split("_", maxsplit=1)[0]


def resource_name(resource_type: str) -> str:
    return resource_type.split("_", maxsplit=1)[-1]
