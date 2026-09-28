# The desktop GPU Ollama (charts/homelab-playground desktop.yaml) in its own release: the desktop
# is powered manually and its Kueue-gated pod cannot become Ready while the desktop is off,
# quarantined or without desktop-compute quota, so this release applies without a Helm wait.
# The main playground release keeps the router backend, egress and UI connections.
resource "helm_release" "playground_desktop" {
  name      = "homelab-playground-desktop"
  namespace = "homelab-inference"
  chart     = "${path.module}/../../../charts/homelab-playground"
  values = [file("${local.config}/playground-values.yaml"), yamlencode({
    desktopOnly   = true
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-playground", "**"))) : filesha256("${path.module}/../../../charts/homelab-playground/${f}")]))
  })]
  wait        = false
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.playground]
  lifecycle {
    prevent_destroy = true
  }
}
