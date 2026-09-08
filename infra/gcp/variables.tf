variable "project_id" { type = string }
variable "project_number" { type = string }
variable "region" { type = string }
variable "network_id" { type = string }
variable "subnet_id" { type = string }
variable "name" {
  type    = string
  default = "talk2data"
}
variable "image" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9.-]+-docker.pkg.dev/.+@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use the reviewed Artifact Registry image by immutable digest."
  }
}
variable "runtime_secrets" {
  type = map(object({ secret = string, version = string }))
  validation {
    condition     = toset(keys(var.runtime_secrets)) == toset(["api", "worker"])
    error_message = "Provide separate pinned API and worker runtime configuration secrets."
  }
}
variable "private_files" {
  type = map(object({ secret = string, version = string, filename = string, mount = string }))
  description = "Approved domain, catalog and entitlement bootstrap mounts; runtime paths must agree."
}
variable "state_dsn_secret" { type = object({ secret = string, version = string }) }
variable "cloud_sql_proxy_image" {
  type = string
  validation {
    condition = can(regex("^gcr.io/cloud-sql-connectors/cloud-sql-proxy@sha256:[a-f0-9]{64}$", var.cloud_sql_proxy_image))
    error_message = "Pin the reviewed official Cloud SQL Auth Proxy image by digest."
  }
}
variable "claude_key_secret" { type = object({ secret = string, version = string }) }
variable "state_tier" {
  type    = string
  default = "db-custom-2-7680"
}
variable "iap_members" {
  type = set(string)
  validation {
    condition     = length(var.iap_members) > 0 && alltrue([for m in var.iap_members : startswith(m, "group:") || startswith(m, "user:")])
    error_message = "Explicit organizational user/group access is required."
  }
}
variable "api_max_instances" {
  type    = number
  default = 4
}
variable "worker_max_instances" {
  type    = number
  default = 4
}
