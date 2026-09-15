variable "kubeconfig_path" {
  type      = string
  sensitive = true
  ephemeral = true
}
provider "helm" {
  kubernetes = { config_path = var.kubeconfig_path }
}
locals {
  config = "${path.module}/../../../config/environments/kubernetes/homelab-ci"
}
resource "helm_release" "kueue" {
  name             = "kueue"
  namespace        = "kueue-system"
  create_namespace = true
  chart            = "${path.module}/.terraform/kueue-0.19.4.tgz"
  version          = "0.19.4"
  values           = [file("${local.config}/kueue-values.yaml"), yamlencode({ homelabRevision = filesha256("${path.module}/../../../scripts/kueue-postrender.py") })]
  postrender       = { binary_path = "${path.module}/../../../scripts/kueue-postrender.py" }
  wait             = true
  timeout          = 600
  max_history      = 5
}
resource "helm_release" "queue" {
  name        = "homelab-queue"
  namespace   = "kueue-system"
  chart       = "${path.module}/../../../charts/homelab-queue"
  values      = [file("${local.config}/pool-values.yaml"), yamlencode({ chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-queue", "**"))) : filesha256("${path.module}/../../../charts/homelab-queue/${f}")])) })]
  depends_on  = [helm_release.kueue]
  wait        = true
  timeout     = 300
  max_history = 5
}
resource "helm_release" "arc" {
  name             = "arc"
  namespace        = "arc-systems"
  create_namespace = true
  chart            = "${path.module}/.terraform/gha-runner-scale-set-controller-0.14.2.tgz"
  version          = "0.14.2"
  values           = [file("${local.config}/arc-controller-values.yaml")]
  depends_on       = [helm_release.queue]
  wait             = true
  timeout          = 600
  max_history      = 5
}
resource "helm_release" "runners" {
  name        = "homelab-talos"
  namespace   = "arc-runners"
  chart       = "${path.module}/.terraform/gha-runner-scale-set-0.14.2.tgz"
  version     = "0.14.2"
  values      = [file("${local.config}/arc-runner-values.yaml")]
  depends_on  = [helm_release.arc]
  wait        = true
  timeout     = 600
  max_history = 5
}
