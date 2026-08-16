resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = var.image_tag_mutability
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = var.scan_on_push
  }

  encryption_configuration {
    encryption_type = var.kms_key_arn == null ? "AES256" : "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = var.tags
}

# Expire untagged images after a retention window, and cap kept tagged images,
# so the registry doesn't grow unbounded.
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = var.preserve_oci_reference_artifacts ? jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent ${var.max_images} signed image subjects and their OCI reference artifacts"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["image-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.max_images
        }
        action = { type = "expire" }
      }
    ]
    }) : jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images older than ${var.untagged_expire_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_expire_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the most recent ${var.max_images} images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.max_images
        }
        action = { type = "expire" }
      }
    ]
  })
}
