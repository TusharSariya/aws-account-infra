resource "helm_release" "postgres_operator" {
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender       = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "cnpg-system"] }
  name             = "cnpg"
  namespace        = "cnpg-system"
  create_namespace = true
  chart            = "${path.module}/.terraform/cloudnative-pg-0.29.0.tgz"
  version          = "0.29.0"
  values           = [file("${local.config}/postgres-operator-values.yaml")]
  wait             = true
  timeout          = 600
  max_history      = 5
  lifecycle { prevent_destroy = true }
}
resource "helm_release" "postgres" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-data"] }
  name       = "apps-db"
  namespace  = "homelab-data"
  chart      = "${path.module}/../../../charts/homelab-postgres"
  values = [file("${local.config}/postgres-values.yaml"), yamlencode({
    code          = { for f in fileset("${path.module}/../../../apps/platform/postgres", "*.py") : f => file("${path.module}/../../../apps/platform/postgres/${f}") }
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-postgres", "**"))) : filesha256("${path.module}/../../../charts/homelab-postgres/${f}")]))
  })]
  wait        = true
  timeout     = 900
  max_history = 5
  depends_on  = [helm_release.postgres_operator]
  lifecycle { prevent_destroy = true }
}
