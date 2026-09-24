# RAG backup storage, catalog, credentials and dedicated key were retired on
# 2026-09-24. Keep image publishing independent of retired backup storage.

# --- ECR repos: one per RAG service image ----------------------------------
module "ecr" {
  source   = "../../../../../modules/aws/ecr_repository"
  for_each = toset(var.ecr_repos)

  name = each.value
  tags = { component = "rag" }
}
