resource "helm_release" "storage_policy" {
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "kube-system"] }
  name       = "homelab-storage-policy"
  namespace  = "kube-system"
  chart      = "${path.module}/charts/storage-policy"
  version    = "0.1.0"
  # Track local chart edits in plans as well as chart version changes.
  set         = [{ name = "sourceRevision", value = sha256(join("", [for f in sort(tolist(fileset("${path.module}/charts/storage-policy", "**"))) : filesha256("${path.module}/charts/storage-policy/${f}")])) }, { name = "mainPlacementRevision", value = local.main_placement_revision }]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.cilium]
  lifecycle { prevent_destroy = true }
}

# Downloaded from the pinned upstream release and checksum verified by CI.
resource "helm_release" "local_path" {
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "local-path-storage"] }
  name        = "local-path-provisioner"
  namespace   = "local-path-storage"
  chart       = "${path.module}/.terraform/local-path-provisioner"
  version     = "0.0.37"
  values      = [file("${path.module}/../../../config/environments/talos/homelab/local-path-values.yaml")]
  wait        = true
  timeout     = 600
  max_history = 5
  depends_on  = [helm_release.storage_policy, talos_machine_configuration_apply.worker]
  lifecycle { prevent_destroy = true }
}
