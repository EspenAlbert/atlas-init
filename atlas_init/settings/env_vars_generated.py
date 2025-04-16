import random

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class _EnvVarsGenerated(BaseSettings):
    model_config = ConfigDict(extra="ignore")  # type: ignore


class AtlasSettings(_EnvVarsGenerated):
    MONGODB_ATLAS_ORG_ID: str = ""
    MONGODB_ATLAS_PRIVATE_KEY: str = ""
    MONGODB_ATLAS_PUBLIC_KEY: str = ""
    MONGODB_ATLAS_BASE_URL: str = "https://cloud-dev.mongodb.com/"

    @property
    def realm_url(self) -> str:
        assert not self.is_mongodbgov_cloud, "realm_url is not supported for mongodbgov cloud"
        if "cloud-dev." in self.MONGODB_ATLAS_BASE_URL:
            return "https://services.cloud-dev.mongodb.com/"
        return "https://services.cloud.mongodb.com/"

    @property
    def is_mongodbgov_cloud(self) -> bool:
        return "mongodbgov" in self.MONGODB_ATLAS_BASE_URL

class AWSSettings(_EnvVarsGenerated):
    AWS_REGION: str = ""
    AWS_PROFILE: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

class TerraformSettings(_EnvVarsGenerated):
    TF_CLI_CONFIG_FILE: str = ""

class RealmSettings(_EnvVarsGenerated):
    MONGODB_REALM_APP_ID: str = ""
    MONGODB_REALM_SERVICE_ID: str = ""
    MONGODB_REALM_FUNCTION_ID: str = ""
    MONGODB_REALM_FUNCTION_NAME: str = ""
    MONGODB_REALM_BASE_URL: str = ""
    RANDOM_INT_100K: str = Field(default_factory=lambda: str(random.randint(0, 100_000)))  # noqa: S311 # not used for cryptographic purposes # nosec


class EnvVarsGenerated(AtlasSettings):
    MONGODB_ATLAS_PROJECT_ID: str = ""


class TFModuleCluster(_EnvVarsGenerated):
    MONGODB_ATLAS_CLUSTER_NAME: str = ""
    MONGODB_ATLAS_CONTAINER_ID: str = ""
    MONGODB_URL: str = ""
