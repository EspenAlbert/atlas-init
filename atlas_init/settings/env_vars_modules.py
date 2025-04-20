from atlas_init.settings.env_vars_generated import _EnvVarsGenerated


class TFModuleAws_S3(_EnvVarsGenerated):
    AWS_S3_BUCKET: str


class TFModuleAws_Vars(_EnvVarsGenerated):
    AWS_ACCESS_KEY_ID: str
    AWS_CUSTOMER_MASTER_KEY_ID: str
    AWS_REGION: str
    AWS_REGION_LOWERCASE: str
    AWS_REGION_UPPERCASE: str
    AWS_SECRET_ACCESS_KEY: str


class TFModuleAws_Vpc(_EnvVarsGenerated):
    AWS_SECURITY_GROUP_ID: str
    AWS_SUBNET_ID: str
    AWS_VPC_CIDR_BLOCK: str
    AWS_VPC_ID: str


class TFModuleCfn(_EnvVarsGenerated):
    CFN_EXAMPLE_EXECUTION_ROLE: str
    MONGODB_ATLAS_PRIVATE_API_KEY: str
    MONGODB_ATLAS_PROFILE: str
    MONGODB_ATLAS_PUBLIC_API_KEY: str
    MONGODB_ATLAS_SECRET_PROFILE: str


class TFModuleCloud_Provider(_EnvVarsGenerated):
    AWS_IAM_ROLE_ARN: str
    IAM_ROLE_ID: str


class TFModuleCluster(_EnvVarsGenerated):
    MONGODB_ATLAS_CLUSTER_NAME: str
    MONGODB_ATLAS_CONTAINER_ID: str
    MONGODB_URL: str


class TFModuleFederated_Vars(_EnvVarsGenerated):
    MONGODB_ATLAS_FEDERATED_GROUP_ID: str
    MONGODB_ATLAS_FEDERATED_IDP_ID: str
    MONGODB_ATLAS_FEDERATED_ORG_ID: str
    MONGODB_ATLAS_FEDERATED_SETTINGS_ASSOCIATED_DOMAIN: str
    MONGODB_ATLAS_FEDERATION_SETTINGS_ID: str


class TFModuleProject_Extra(_EnvVarsGenerated):
    MONGODB_ATLAS_ORG_API_KEY_ID: str
    MONGODB_ATLAS_TEAMS_IDS: str
    MONGODB_ATLAS_TEAM_ID: str


class TFModuleStream_Instance(_EnvVarsGenerated):
    MONGODB_ATLAS_STREAM_INSTANCE_ID: str
    MONGODB_ATLAS_STREAM_INSTANCE_NAME: str


class TFModuleVpc_Peering(_EnvVarsGenerated):
    AWS_ACCOUNT_ID: str
    AWS_REGION: str
    AWS_VPC_CIDR_BLOCK: str
    AWS_VPC_ID: str


class TFModuleVpc_Privatelink(_EnvVarsGenerated):
    MONGODB_ATLAS_PRIVATE_ENDPOINT_DNS_NAME: str
    MONGODB_ATLAS_PRIVATE_ENDPOINT_ID: str
