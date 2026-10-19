# State is local (terraform.tfstate in this folder, git-ignored). There is no backend block.
terraform {
  required_version = ">= 1.16"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Region and credentials come from AWS_REGION and AWS_PROFILE. Nothing is hard-coded here.
provider "aws" {
  default_tags {
    tags = {
      Project = "doc-rag-mock"
    }
  }
}

locals {
  prefix = "doc-rag-mock"
  # The bucket already exists and is not managed by Terraform (destroy must not delete it).
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
}
