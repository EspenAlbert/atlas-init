

resource "mongodbatlas_federated_database_instance" "this" {
  dynamic "cloud_provider_config" {
    for_each = var.cloud_provider_config == null ? [] : [var.cloud_provider_config]
    content {
      dynamic "aws" {
        for_each = var.aws == null ? [] : [var.aws]
        content {
          role_id        = aws.value.role_id
          test_s3_bucket = aws.value.test_s3_bucket
        }
      }
      dynamic "azure" {
        for_each = var.azure == null ? [] : [var.azure]
        content {
          role_id = azure.value.role_id
        }
      }
    }
  }
  dynamic "data_process_region" {
    for_each = var.data_process_region == null ? [] : [var.data_process_region]
    content {
      cloud_provider = data_process_region.value.cloud_provider
      region         = data_process_region.value.region
    }
  }
  id         = var.id
  name       = var.name
  project_id = var.project_id
  dynamic "storage_databases" {
    for_each = var.storage_databases == null ? [] : [var.storage_databases]
    content {
      name = storage_databases.value.name
      dynamic "collections" {
        for_each = var.collections == null ? [] : [var.collections]
        content {
          name = collections.value.name
          dynamic "data_sources" {
            for_each = var.data_sources == null ? [] : [var.data_sources]
            content {
              allow_insecure        = data_sources.value.allow_insecure
              collection            = data_sources.value.collection
              collection_regex      = data_sources.value.collection_regex
              database              = data_sources.value.database
              database_regex        = data_sources.value.database_regex
              dataset_name          = data_sources.value.dataset_name
              default_format        = data_sources.value.default_format
              path                  = data_sources.value.path
              provenance_field_name = data_sources.value.provenance_field_name
              store_name            = data_sources.value.store_name
              urls                  = data_sources.value.urls
            }
          }
        }
      }
      dynamic "views" {
        for_each = var.views == null ? [] : [var.views]
        content {
        }
      }
    }
  }
  dynamic "storage_stores" {
    for_each = var.storage_stores == null ? [] : [var.storage_stores]
    content {
      additional_storage_classes = storage_stores.value.additional_storage_classes
      allow_insecure             = storage_stores.value.allow_insecure
      bucket                     = storage_stores.value.bucket
      cluster_name               = storage_stores.value.cluster_name
      default_format             = storage_stores.value.default_format
      delimiter                  = storage_stores.value.delimiter
      include_tags               = storage_stores.value.include_tags
      name                       = storage_stores.value.name
      prefix                     = storage_stores.value.prefix
      project_id                 = storage_stores.value.project_id
      provider                   = storage_stores.value.provider
      public                     = storage_stores.value.public
      region                     = storage_stores.value.region
      urls                       = storage_stores.value.urls
      dynamic "read_preference" {
        for_each = var.read_preference == null ? [] : [var.read_preference]
        content {
          max_staleness_seconds = read_preference.value.max_staleness_seconds
          mode                  = read_preference.value.mode
          dynamic "tag_sets" {
            for_each = var.tag_sets == null ? [] : [var.tag_sets]
            content {
              dynamic "tags" {
                for_each = var.tags == null ? [] : [var.tags]
                content {
                  name  = tags.value.name
                  value = tags.value.value
                }
              }
            }
          }
        }
      }
    }
  }
}

