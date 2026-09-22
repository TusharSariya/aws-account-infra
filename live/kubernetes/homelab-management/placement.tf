locals {
  main_placement_revision = sha256(join("", [
    filesha256("${path.module}/../../../kubernetes/platform/main/placement/plan.py"),
    filesha256("${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py")
  ]))
}
