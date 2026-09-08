terraform {
  required_version = ">= 1.13, < 2"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 7.0, < 8.0"
    }
  }
  # Supply an approved private remote backend through -backend-config at activation.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
