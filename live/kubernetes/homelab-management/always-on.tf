resource "helm_release" "always_on" {
  depends_on = [helm_release.queue]
  name       = "homelab-always-on"
  namespace  = "homelab-platform"
  chart      = "${path.module}/../../../charts/homelab-always-on"
  values = [yamlencode({
    gatewayCode = file("${path.module}/../../../controllers/homelab-capacity/src/homelab_capacity/gateway.py")
    gateways    = jsondecode(file("${path.module}/../../../platform/automatic-power/gateways.json"))
  chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-always-on", "**"))) : filesha256("${path.module}/../../../charts/homelab-always-on/${f}")])) })]
  wait        = true
  timeout     = 300
  max_history = 5
  lifecycle { prevent_destroy = true }
}
