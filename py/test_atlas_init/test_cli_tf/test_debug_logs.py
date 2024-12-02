from atlas_init.cli_tf.debug_logs import (
    PathHeadersPayload,
    SDKRoundtrip,
    StatusHeadersResponse,
)


_req1 = PathHeadersPayload(
    method="GET",
    path="/api/atlas/v2/groups/6746cef5aef48d1cb2658a7f/ipAddresses",
    http_protocol="HTTP/1.1",
    headers={
        "Host": "cloud-dev.mongodb.com",
        "User-Agent": "terraform-provider-mongodbatlas/devel Terraform/1.9.6",
        "Accept": "application/vnd.atlas.2023-01-01+json",
        "Accept-Encoding": "gzip",
    },
    text="",
)
_resp1 = StatusHeadersResponse(
    http_protocol="HTTP/2.0",
    status=200,
    status_text="OK",
    headers={
        "Content-Type": "application/vnd.atlas.2023-01-01+json;charset=utf-8",
        "Date": "Wed, 27 Nov 2024 07:49:14 GMT",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Server": "mdbws",
        "Strict-Transport-Security": "max-age=31536000; includeSubdomains;",
        "Vary": "Accept-Encoding",
        "X-Content-Type-Options": "nosniff",
        "X-Envoy-Upstream-Service-Time": "71",
        "X-Frame-Options": "DENY",
        "X-Java-Method": "ApiAtlasGroupsResource::getIPAddresses",
        "X-Java-Version": "17.0.12+7",
        "X-Mongodb-Service-Version": "gitHash=6e0137abb37d10f0d6179c1d69ee492495b18e9d; versionString=master",
        "X-Permitted-Cross-Domain-Policies": "none",
    },
    text='{\n "groupId": "6746cef5aef48d1cb2658a7f",\n "services": {\n  "clusters": []\n }\n}',
)


def test_java_method_match():
    rt = SDKRoundtrip(request=_req1, response=_resp1, resp_index=0, step_number=0)
    assert rt.java_method_match
