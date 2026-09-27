resource "helm_release" "playground" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-models"] }
  name       = "homelab-playground"
  namespace  = "homelab-models"
  chart      = "${path.module}/../../../charts/homelab-playground"
  values = [file("${local.config}/playground-values.yaml"), yamlencode({
    routerCode    = { for f in fileset("${path.module}/../../../apps/platform/playground", "*.py") : f => file("${path.module}/../../../apps/platform/playground/${f}") }
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-playground", "**"))) : filesha256("${path.module}/../../../charts/homelab-playground/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.ai]
  lifecycle {
    prevent_destroy = true
  }
}
