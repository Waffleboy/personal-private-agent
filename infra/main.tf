terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"

  # Hash of everything that affects the image, used as the image tag.
  source_files = sort(setunion(
    fileset("${path.module}/..", "Dockerfile"),
    fileset("${path.module}/..", "requirements.txt"),
    fileset("${path.module}/..", "src/memory_bot/*.py"),
  ))
  source_hash = substr(sha1(join("", [
    for f in local.source_files :
    filesha1("${path.module}/../${f}")
  ])), 0, 12)

  image_uri = "${aws_ecr_repository.bot.repository_url}:${local.source_hash}"
}

resource "aws_ecr_repository" "bot" {
  name                 = var.name_prefix
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "null_resource" "image_push" {
  triggers = {
    source_hash = local.source_hash
    repo_url    = aws_ecr_repository.bot.repository_url
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      aws ecr get-login-password --region ${var.aws_region} \
        | docker login --username AWS --password-stdin ${local.registry}
      docker build -t ${local.image_uri} .
      docker push ${local.image_uri}
    EOT
  }
}
