from atlas_init.cli_tf.changelog import convert_to_changelog


_example1 = """\
rs=mongodbatlas_federated_settings_org_config
- feat(rs+ds+dsp): Adds `data_access_identity_provider_ids`
- feat(rs): Adds `user_conflicts`
- feat(rs): Supports detaching and updating the `identity_provider_id`
"""

changelog = """\
```release-note:enhancement
data-source/mongodbatlas_federated_settings_org_config: Adds `data_access_identity_provider_ids`
```

```release-note:enhancement
data-source/mongodbatlas_federated_settings_org_configs: Adds `data_access_identity_provider_ids`
```

```release-note:enhancement
resource/mongodbatlas_federated_settings_org_config: Adds `data_access_identity_provider_ids`
```

```release-note:enhancement
resource/mongodbatlas_federated_settings_org_config: Adds `user_conflicts`
```

```release-note:enhancement
resource/mongodbatlas_federated_settings_org_config: Supports detaching and updating the `identity_provider_id`
```"""



def test_convert_to_changelog():
    output = convert_to_changelog(_example1)
    assert output == changelog
