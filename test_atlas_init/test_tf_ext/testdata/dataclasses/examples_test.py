from . import mongodbatlas_advanced_cluster_custom

ResourceExt = mongodbatlas_advanced_cluster_custom.ResourceExt
CustomSpec = mongodbatlas_advanced_cluster_custom.CustomSpec
SpecRegion = mongodbatlas_advanced_cluster_custom.SpecRegion
VARIABLE_PLACEHOLDER = "var."
VARIABLES: dict[str, str] = {
    "project_id": VARIABLE_PLACEHOLDER,
}
EXAMPLES = {
    "example1": ResourceExt(
        **VARIABLES,
        electable=CustomSpec(
            regions=[SpecRegion(provider_name="AWS", name="US_EAST_1", node_count=3)],
            disk_size_gb=50,
        ),
    ),
}
