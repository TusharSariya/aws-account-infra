variable "name" {
  type        = string
  description = "ECR repository name (e.g. graph-rag-query)."
}

variable "image_tag_mutability" {
  type        = string
  default     = "IMMUTABLE"
  description = "IMMUTABLE prevents overwriting an existing tag (recommended for reproducible deploys)."

  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be MUTABLE or IMMUTABLE."
  }
}

variable "scan_on_push" {
  type    = bool
  default = true
}

variable "kms_key_arn" {
  type        = string
  default     = null
  description = "If set, images are encrypted with this KMS key; otherwise AES256."
}

variable "force_delete" {
  type        = bool
  default     = false
  description = "Allow deleting the repo even if it still contains images."
}

variable "untagged_expire_days" {
  type    = number
  default = 14
}

variable "max_images" {
  type        = number
  default     = 20
  description = "Keep at most this many images total (older ones expire)."
}

variable "preserve_oci_reference_artifacts" {
  type        = bool
  default     = false
  description = "Keep untagged OCI signature, SBOM, and provenance manifests; expire only image-* subjects by count."
}

variable "tags" {
  type    = map(string)
  default = {}
}
