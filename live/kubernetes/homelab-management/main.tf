variable "kubeconfig_path" {
  type      = string
  sensitive = true
  ephemeral = true
}
provider "helm" {
  kubernetes = { config_path = var.kubeconfig_path }
}
locals {
  apps_config = "${path.module}/../../../config/environments/kubernetes/homelab"
  pool        = yamldecode(file("${path.module}/../../../config/environments/kubernetes/homelab-ci/pool-values.yaml"))
  config      = "${path.module}/../../../config/environments/kubernetes/homelab-ci"
}
resource "helm_release" "kueue" {
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
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
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "kueue-system"] }
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
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender       = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "arc-systems"] }
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
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "arc-runners"] }
  for_each   = local.runner_catalog
  name       = each.key
  namespace  = "arc-runners"
  chart      = "${path.module}/.terraform/gha-runner-scale-set-0.14.2.tgz"
  version    = "0.14.2"
  values     = [yamlencode(local.runner_values[each.key])]
  lifecycle {
    precondition {
      condition = (
        can(regex("^homelab-talos(-[a-z0-9]+)*$", each.key)) && length(each.key) <= 45 &&
        each.value.cpu > 0 && each.value.cpu <= tonumber(local.pool.cpu) && floor(each.value.cpu * 1000) == each.value.cpu * 1000 &&
        each.value.memory > 0 && each.value.memory <= tonumber(trimsuffix(local.pool.memory, "Gi")) * 1024 && floor(each.value.memory) == each.value.memory &&
        each.value.scratch > 0 && each.value.scratch <= tonumber(trimsuffix(local.pool.scratch, "Gi")) * 1024 && floor(each.value.scratch) == each.value.scratch &&
        (!each.value.docker || (each.value.cpu >= 0.1 && each.value.memory >= 128 && each.value.scratch >= 1024))
      )
      error_message = "Runner catalog requires a valid scale-set name and positive whole-Pod budgets within the configured shared pool; Docker must also cover its initialization peak."
    }
  }

  depends_on  = [helm_release.arc]
  wait        = true
  timeout     = 600
  max_history = 5
}

resource "helm_release" "tailscale_operator" {
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "tailscale"] }
  name        = "tailscale-operator"
  namespace   = "tailscale"
  chart       = "${path.module}/.terraform/tailscale-operator-1.102.3.tgz"
  version     = "1.102.3"
  values      = [file("${local.apps_config}/operator-values.yaml")]
  wait        = true
  timeout     = 600
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}
resource "helm_release" "pihole" {
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-services"] }
  name        = "pihole"
  namespace   = "homelab-services"
  chart       = "${path.module}/.terraform/pihole-2.38.0.tgz"
  version     = "2.38.0"
  values      = [file("${local.apps_config}/pihole-values.yaml")]
  wait        = true
  timeout     = 600
  max_history = 5
  depends_on  = [helm_release.tailscale_operator, helm_release.always_on]
}

resource "helm_release" "lifecycle" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-platform"] }
  name       = "homelab-lifecycle"
  namespace  = "homelab-platform"
  chart      = "${path.module}/../../../charts/homelab-lifecycle"
  values = [file("${local.apps_config}/lifecycle-values.yaml"), yamlencode({
    code = merge(
      { for f in fileset("${path.module}/../../../apps/platform/storage", "*.py") : f => file("${path.module}/../../../apps/platform/storage/${f}") },
      { for f in fileset("${path.module}/../../../apps/platform/lifecycle", "*.py") : f => file("${path.module}/../../../apps/platform/lifecycle/${f}") }
    )
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-lifecycle", "**"))) : filesha256("${path.module}/../../../charts/homelab-lifecycle/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "argo" {
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender       = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-jobs"] }
  name             = "argo-workflows"
  namespace        = "homelab-jobs"
  create_namespace = true
  chart            = "${path.module}/.terraform/argo-workflows-2.0.5.tgz"
  version          = "2.0.5"
  values           = [file("${local.apps_config}/argo-values.yaml")]
  wait             = true
  timeout          = 600
  max_history      = 5
  depends_on       = [helm_release.lifecycle]
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "jobs" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-jobs"] }
  name       = "homelab-jobs"
  namespace  = "homelab-jobs"
  chart      = "${path.module}/../../../charts/homelab-jobs"
  values = [yamlencode({
    code          = { for f in fileset("${path.module}/../../../apps/platform/jobs", "*.py") : f => file("${path.module}/../../../apps/platform/jobs/${f}") }
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-jobs", "**"))) : filesha256("${path.module}/../../../charts/homelab-jobs/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.argo]
  lifecycle {
    prevent_destroy = true
  }
}
