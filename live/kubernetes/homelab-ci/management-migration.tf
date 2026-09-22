# Ownership transfers to homelab-management; never uninstall during migration.
removed {
  from = helm_release.kueue
  lifecycle { destroy = false }
}
removed {
  from = helm_release.queue
  lifecycle { destroy = false }
}
removed {
  from = helm_release.arc
  lifecycle { destroy = false }
}
removed {
  from = helm_release.runners
  lifecycle { destroy = false }
}
