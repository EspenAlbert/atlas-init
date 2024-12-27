from pydantic_settings import BaseSettings


class AtlasSettings(BaseSettings):
    MONGODB_ATLAS_ORG_ID: str
    MONGODB_ATLAS_PRIVATE_KEY: str
    MONGODB_ATLAS_PUBLIC_KEY: str
    MONGODB_ATLAS_BASE_URL: str = "https://cloud-dev.mongodb.com/"


class RealmSettings(BaseSettings):
    MONGODB_REALM_APP_ID: str
    MONGODB_REALM_SERVICE_ID: str
    MONGODB_REALM_FUNCTION_ID: str
    MONGODB_REALM_FUNCTION_NAME: str
    MONGODB_REALM_BASE_URL: str


class EnvVarsGenerated(AtlasSettings):
    MONGODB_ATLAS_PROJECT_ID: str


class TFModuleCluster(BaseSettings):
    MONGODB_ATLAS_CLUSTER_NAME: str
    MONGODB_ATLAS_CONTAINER_ID: str
    MONGODB_URL: str
