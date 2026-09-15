# Catalog CPU is cores; memory and scratch are MiB. Sizes are reviewed values,
# not fixed tiers. Kubernetes effective Pod requests include restartable init.
locals {
  runner_catalog = jsondecode(file("${local.config}/runner-catalog.json"))
  runner_base    = yamldecode(file("${local.config}/arc-runner-values.yaml"))
  runner_allocations = {
    for name, config in local.runner_catalog : name => {
      cpu                 = "${ceil(config.cpu * 1000 / (config.docker ? 2 : 1))}m"
      memory              = "${config.memory / (config.docker ? 2 : 1)}Mi"
      "ephemeral-storage" = "${config.scratch / (config.docker ? 2 : 1)}Mi"
    }
  }
  runner_values = {
    for name, config in local.runner_catalog : name => merge(local.runner_base, {
      runnerScaleSetName = name
      template = merge(local.runner_base.template, {
        spec = merge(local.runner_base.template.spec, {
          containers = [merge(local.runner_base.template.spec.containers[0], {
            resources = { requests = local.runner_allocations[name], limits = local.runner_allocations[name] }
            env       = config.docker ? local.runner_base.template.spec.containers[0].env : []
            volumeMounts = config.docker ? local.runner_base.template.spec.containers[0].volumeMounts : [
              { name = "scratch", mountPath = "/home/runner/_work", subPath = "work" }
            ]
          })]
          initContainers = [for container in [
            local.runner_base.template.spec.initContainers[0],
            merge(local.runner_base.template.spec.initContainers[1], {
              resources = {
                requests = merge(local.runner_allocations[name], { cpu = "${floor(config.cpu * 1000 / 2)}m" })
                limits   = merge(local.runner_allocations[name], { cpu = "${floor(config.cpu * 1000 / 2)}m" })
              }
            })
          ] : container if config.docker]
          volumes = [{ name = "scratch", emptyDir = { sizeLimit = "${config.scratch}Mi" } }]
        })
      })
    })
  }
}

# Preserve the existing Helm release and registered scale-set identity.
moved {
  from = helm_release.runners
  to   = helm_release.runners["homelab-talos"]
}
