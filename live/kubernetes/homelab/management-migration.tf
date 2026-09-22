# Ownership transfers to homelab-management; never uninstall during migration.
removed {
  from = helm_release.tailscale_operator
  lifecycle { destroy = false }
}
removed {
  from = helm_release.pihole
  lifecycle { destroy = false }
}
removed {
  from = helm_release.lifecycle
  lifecycle { destroy = false }
}
removed {
  from = helm_release.argo
  lifecycle { destroy = false }
}
removed {
  from = helm_release.jobs
  lifecycle { destroy = false }
}
