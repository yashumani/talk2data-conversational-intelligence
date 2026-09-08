# Reference deployment. No identifiers or credentials are inferred from CSV or application code.
resource "google_compute_global_address" "state_range" {
  name          = "${var.name}-state-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 24
  network       = var.network_id
}

resource "google_service_networking_connection" "state" {
  network                 = var.network_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.state_range.name]
}

resource "google_sql_database_instance" "state" {
  name                = "${var.name}-state"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true
  depends_on          = [google_service_networking_connection.state]
  settings {
    tier                        = var.state_tier
    availability_type           = "REGIONAL"
    deletion_protection_enabled = true
    disk_autoresize             = true
    disk_type                   = "PD_SSD"
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings { retained_backups = 14 }
    }
  }
  lifecycle { prevent_destroy = true }
}

resource "google_sql_database" "application" {
  name     = "talk2data_state"
  instance = google_sql_database_instance.state.name
}

resource "google_service_account" "runtime" {
  for_each   = toset(["api", "worker"])
  account_id = "${var.name}-${each.key}"
}

resource "google_project_iam_member" "sql_client" {
  for_each = google_service_account.runtime
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${each.value.email}"
}

locals {
  shared_secrets = merge(var.private_files, {
    state = var.state_dsn_secret
    claude = var.claude_key_secret
  })
  secret_grants = merge([for role in ["api", "worker"] : {
    for name, secret in merge(local.shared_secrets, { runtime = var.runtime_secrets[role] }) :
    "${role}-${name}" => { role = role, secret = secret.secret }
  }]...)
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secret_grants
  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value.role].email}"
}

resource "google_cloud_run_v2_service" "runtime" {
  for_each            = toset(["api", "worker"])
  name                = "${var.name}-${each.key}"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  iap_enabled         = each.key == "api"
  deletion_protection = true
  template {
    service_account                  = google_service_account.runtime[each.key].email
    max_instance_request_concurrency = 16
    timeout                          = "300s"
    scaling {
      min_instance_count = 1
      max_instance_count = each.key == "api" ? var.api_max_instances : var.worker_max_instances
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = var.network_id
        subnetwork = var.subnet_id
      }
    }
    containers {
      name = "application"
      image = var.image
      depends_on = ["cloud-sql-proxy"]
      ports { container_port = 8000 }
      resources {
        limits   = { cpu = "2", memory = "2Gi" }
        cpu_idle = false
      }
      env {
        name  = "T2D_INTERNAL_CONFIG_FILE"
        value = "/runtime/runtime.json"
      }
      env {
        name = "T2D_STATE_DSN"
        value_source {
          secret_key_ref {
            secret  = var.state_dsn_secret.secret
            version = var.state_dsn_secret.version
          }
        }
      }
      env {
        name = "T2D_CLAUDE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.claude_key_secret.secret
            version = var.claude_key_secret.version
          }
        }
      }
      volume_mounts {
        name       = "runtime"
        mount_path = "/runtime"
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "volume_mounts" {
        for_each = var.private_files
        content {
          name       = volume_mounts.key
          mount_path = volume_mounts.value.mount
        }
      }
      startup_probe {
        http_get { path = "/health/live" }
        period_seconds    = 5
        failure_threshold = 24
      }
      liveness_probe {
        http_get { path = "/health/live" }
        period_seconds = 30
      }
    }
    containers {
      name  = "cloud-sql-proxy"
      image = var.cloud_sql_proxy_image
      args = ["--private-ip", "--unix-socket=/cloudsql", "--health-check", "--http-address=0.0.0.0",
              "--http-port=9090", google_sql_database_instance.state.connection_name]
      resources {
        limits = { cpu = "1", memory = "256Mi" }
        cpu_idle = false
      }
      volume_mounts {
        name = "cloudsql"
        mount_path = "/cloudsql"
      }
      startup_probe {
        http_get {
          path = "/startup"
          port = 9090
        }
        period_seconds = 5
        failure_threshold = 24
      }
    }
    volumes {
      name = "cloudsql"
      empty_dir {
        medium = "MEMORY"
        size_limit = "256Mi"
      }
    }
    volumes {
      name = "runtime"
      secret {
        secret = var.runtime_secrets[each.key].secret
        items {
          path    = "runtime.json"
          version = var.runtime_secrets[each.key].version
        }
      }
    }
    dynamic "volumes" {
      for_each = var.private_files
      content {
        name = volumes.key
        secret {
          secret = volumes.value.secret
          items {
            path    = volumes.value.filename
            version = volumes.value.version
          }
        }
      }
    }
  }
  depends_on = [google_project_iam_member.sql_client, google_secret_manager_secret_iam_member.runtime]
}

resource "google_cloud_run_v2_service_iam_member" "iap" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.runtime["api"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${var.project_number}@gcp-sa-iap.iam.gserviceaccount.com"
}

resource "google_iap_web_cloud_run_service_iam_member" "users" {
  for_each               = var.iap_members
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.runtime["api"].name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}

output "state_connection_name" { value = google_sql_database_instance.state.connection_name }
output "runtime_identities" { value = { for role, account in google_service_account.runtime : role => account.email } }
