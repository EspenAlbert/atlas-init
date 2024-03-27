from functools import lru_cache
from boto3.session import Session

from mypy_boto3_cloudformation import CloudFormationClient


@lru_cache
def cloud_formation_client(region_name: str = "") -> CloudFormationClient:
    return Session(region_name=region_name).client("cloudformation")  # type: ignore


def deregister_cfn_resource_type(type_name: str, deregister: bool):
    regions = "af-south-1,ap-east-1,ap-northeast-1,ap-northeast-2,ap-northeast-3,ap-south-1,ap-southeast-1,ap-southeast-2,ap-southeast-3,ca-central-1,eu-central-1,eu-north-1,eu-south-1,eu-west-1,eu-west-2,eu-west-3,me-south-1,sa-east-1,us-east-1,us-east-2,us-west-1,us-west-2,ap-south-2,ap-southeast-4,eu-central-2,eu-south-2,me-central-1,il-central-1".split(
        ","
    )
    for region in regions:
        try:
            default_version_arn = None
            client = cloud_formation_client(region)
            for version in client.list_type_versions(
                Type="RESOURCE", TypeName=type_name
            )["TypeVersionSummaries"]:
                print(f"found version: {version} for {type_name} in {region}")
                if not deregister:
                    continue
                arn = version["Arn"]
                if version["IsDefaultVersion"]:
                    default_version_arn = arn.rsplit("/", maxsplit=1)[0]
                else:
                    print(f"deregistering: {arn}")
                    client.deregister_type(Arn=arn)
            if default_version_arn is not None:
                print(f"deregistering default-arn: {arn}")
                client.deregister_type(Arn=default_version_arn)
        except Exception as e:
            if "The type does not exist" in repr(e):
                print(f"type={type_name} not found in {region}")
                continue
            raise e

iam_policy = """\
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "*",
            "Effect": "Allow"
        }
    ]
}"""
iam_trust_policy = """\
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": [
                    "cloudformation.amazonaws.com",
                    "resources.cloudformation.amazonaws.com",
                    "lambda.amazonaws.com"
                ]
            },
            "Action": "sts:AssumeRole"
        }
    ]
}"""

def activate_resource_type(type_name: str, region: str):
    client: CloudFormationClient = cloud_formation_client(region)
    # prefix = type_name.split(":", maxsplit=1)[0]
    prefix = type_name
    print(f"finding public 3rd party for {prefix}")
    # todo: Clean me up, and use this to find the arn
    # can also use "IsActivated" to be idempotent, and double-check the "LatestPublicVersion" and "LastUpdated"

    # todo: can use the static  arn:aws:iam::358363220050:role/mongodb-atlas-streamconnection-role-s-ExecutionRole-L8Pmt3uDFonT
    # but most likely will prefer to create this manually too

    public_types = client.list_types(
        Visibility="PUBLIC",
        Filters={"Category": "THIRD_PARTY", "TypeNamePrefix": prefix},
        MaxResults=100,
    )
    print(public_types)
    next_token = public_types["NextToken"]
    for t in public_types["TypeSummaries"]:
        print(t)

    while next_token:
        public_types2 = client.list_types(
            Visibility="PUBLIC",
            Filters={"Category": "THIRD_PARTY", "TypeNamePrefix": prefix},
            MaxResults=100,
            NextToken=next_token,
        )
        next_token = public_types2.get("NextToken", "")
        for t in public_types2["TypeSummaries"]:
            print(t)
    # response = client.activate_type(
    #     Type="RESOURCE",
    #     PublicTypeArn="arn:aws:cloudformation:eu-south-2::type/resource/bb989456c78c398a858fef18f2ca1bfc1fbba082/MongoDB-Atlas-StreamConnection",
    #     ExecutionRoleArn="arn:aws:iam::358363220050:role/mongodb-atlas-streamconnection-role-s-ExecutionRole-L8Pmt3uDFonT"
    # )
    # print(f"activate response: {response}")


if __name__ == "__main__":
    # deregister_cfn_resource_type("MongoDB::Atlas::StreamConnection", deregister=True)
    activate_resource_type("MongoDB::Atlas::StreamConnection", "eu-south-2")
