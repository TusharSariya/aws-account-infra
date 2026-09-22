resource "helm_release" "cache" {
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender       = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-cache"] }
  name             = "homelab-cache"
  namespace        = "homelab-cache"
  create_namespace = true
  chart            = "${path.module}/../../../charts/homelab-cache"
  values = [yamlencode({
    configure         = true
    repositories      = jsondecode(file("${local.config}/cache-repositories.json"))
    configurationCode = file("${path.module}/../../../apps/platform/cache/configure.py")
    monitorCode       = file("${path.module}/../../../apps/platform/cache/monitor.py")
    volumes           = jsondecode(file("${local.config}/cache-storage.json"))
    chartRevision     = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-cache", "**"))) : filesha256("${path.module}/../../../charts/homelab-cache/${f}")]))
  })]
  wait        = true
  timeout     = 1200
  max_history = 5
  lifecycle { prevent_destroy = true }
}
