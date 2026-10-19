# Values come from .env through TF_VAR_* (see README). Only force_fail_step has a default.

variable "bucket_name" {
  description = "Existing S3 bucket (S3_BUCKET). Terraform only turns on its EventBridge notifications."
  type        = string
}

variable "pinecone_index" {
  description = "Pinecone dense index name (PINECONE_INDEX)."
  type        = string
}

variable "pinecone_namespace" {
  description = "Pinecone namespace the pipeline writes to, e.g. pipeline."
  type        = string

  validation {
    condition     = length(var.pinecone_namespace) > 0
    error_message = "Set a namespace; the default namespace holds the data indexed by hand in M3."
  }
}

variable "pinecone_embed_model" {
  description = "Pinecone embedding model (PINECONE_EMBED_MODEL). Must match the index."
  type        = string
}

variable "force_fail_step" {
  description = "Test only: this step raises TransientError (register, start_extraction, check_extraction, save_extraction, index). Empty means off."
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "register", "start_extraction", "check_extraction", "save_extraction", "index"], var.force_fail_step)
    error_message = "Use \"\" or one of the step names."
  }
}
