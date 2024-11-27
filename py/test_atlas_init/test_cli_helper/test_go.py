from atlas_init.cli_helper.go import move_failed_logs_to_error_dir


failures = {
    "TestAccClusterAdvancedCluster_pinnedFCVWithVersionUpgradeAndDowngrade",
    "TestAccClusterAdvancedClusterConfig_symmetricShardedNewSchemaToAsymmetricAddingRemovingShard",
    "TestAccAdvancedCluster_replicaSetScalingStrategyAndRedactClientLogData",
    "TestAccClusterAdvancedClusterConfig_replicationSpecsAutoScaling",
    "TestAccClusterAdvancedClusterConfig_asymmetricGeoShardedNewSchemaAddingRemovingShard",
    "TestAccClusterAdvancedClusterConfig_singleShardedTransitionToOldSchemaExpectsError",
    "TestAccClusterAdvancedClusterConfig_symmetricShardedOldSchema",
    "TestAccClusterAdvancedCluster_priorityNewSchema",
    "TestAccAdvancedCluster_replicaSetScalingStrategyAndRedactClientLogDataOldSchema",
    "TestAccClusterAdvancedCluster_advancedConfig",
    "TestAccClusterAdvancedClusterConfig_shardedTransitionFromOldToNewSchema",
    "TestAccClusterAdvancedClusterConfig_asymmetricShardedNewSchema",
    "TestAccClusterAdvancedClusterConfig_symmetricGeoShardedOldSchema",
    "TestAccClusterAdvancedCluster_defaultWrite",
    "TestAccClusterAdvancedClusterConfig_selfManagedSharding",
    "TestAccClusterAdvancedClusterConfig_geoShardedTransitionFromOldToNewSchema",
    "TestAccClusterAdvancedCluster_pausedToUnpaused",
    "TestAccClusterAdvancedCluster_withTags",
    "TestAccClusterAdvancedCluster_priorityOldSchema",
    "TestAccClusterAdvancedClusterConfig_symmetricShardedOldSchemaDiskSizeGBAtElectableLevel",
    "TestAccClusterAdvancedClusterConfig_replicationSpecsAnalyticsAutoScaling",
    "TestAccClusterAdvancedCluster_singleShardedMultiCloud",
}


def test_move_failed_tests():
    move_failed_logs_to_error_dir(failures)
