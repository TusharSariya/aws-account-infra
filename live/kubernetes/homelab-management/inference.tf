resource "helm_release" "inference" {
  name      = "homelab-inference"
  namespace = "kueue-system"
  chart     = "${path.module}/../../../charts/homelab-inference"
  values = [file("${local.apps_config}/inference-values.yaml"), yamlencode({
    code          = { for f in fileset("${path.module}/../../../apps/platform/inference", "*.py") : f => file("${path.module}/../../../apps/platform/inference/${f}") }
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-inference", "**"))) : filesha256("${path.module}/../../../charts/homelab-inference/${f}")]))
  })]
  depends_on  = [helm_release.queue, helm_release.always_on]
  wait        = true
  timeout     = 300
  max_history = 5
}
