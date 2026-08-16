module "ecr" {
  source = "../../../../../modules/aws/ecr_repository"

  name = "court-booker"
  tags = { component = "court-booker" }

  preserve_oci_reference_artifacts = true
}
