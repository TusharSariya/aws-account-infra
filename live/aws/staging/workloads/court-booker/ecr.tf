module "ecr" {
  source = "../../../../../modules/aws/ecr_repository"

  name = "court-booker"
  tags = { component = "court-booker" }
}
