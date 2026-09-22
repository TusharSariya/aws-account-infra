> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

I researched each of the six areas below. The main conclusions:

- Use Talos system extensions for the GPU drivers, with the NVIDIA device plugin. Hold off on DRA for now.
- Keep Kueue for queueing.
- Scale from zero with KEDA.
- Waking a sleeping server needs a small controller you write yourself.
- Serve models with plain vLLM or Ollama.
- Use the CPU manager only on the GPU node.

Where I couldn't check a claim against a primary source, it is marked **[unverified]**.

---

# AI workloads on the Talos homelab: 2026 recommendations

**Current versions (checked):**
- **Talos 1.14.0** (released 2026-09-03) ships **Kubernetes 1.37.0**. Your repo is still on 1.13.9. https://github.com/siderolabs/talos/releases/tag/v1.14.0
- **Kubernetes 1.37** was released 2026-08-26. https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/

## 1. GPU on Talos

**Recommendation:**
- Run the GPU server as **bare-metal Talos**, not a Proxmox VM with the GPU passed through.
- Install the NVIDIA extensions from Image Factory and the **NVIDIA device plugin**. Either install it on its own or through GPU Operator (v26.3.1 or later) with its driver and toolkit parts turned off.
- Use **time-slicing** to share the GPU. Don't adopt DRA yet.

**Why and how:**
- **Talos setup.** The Sidero docs say to use `nonfree-kmod-nvidia` plus `nvidia-container-toolkit`. Signed open-module variants also exist (`nvidia-open-gpu-kernel-modules-production`).
  - On Talos 1.14 you load `nvidia`, `nvidia_uvm`, `nvidia_drm` and `nvidia_modeset` through separate `KernelModuleConfig` documents.
  - GPU Operator needs `driver.enabled=false`, `toolkit.enabled=false` and `hostPaths.driverInstallDir=/usr/local`.
  - https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/hardware-and-drivers/nvidia-gpu-proprietary
- **GPU Operator v26.7.0.** It bundles device plugin v0.20.0, DRA driver v0.5.0, NFD v0.19.0 and MIG manager v0.15.0. CDI is on by default. https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/release-notes.html
- **DRA status.**
  - The core API went GA in Kubernetes 1.34 and is locked on from 1.35.
  - In 1.36, Prioritized List went GA. Partitionable Devices and Consumable Capacity went beta. https://bex.co/blog/2026/07/30/kubernetes-dra-ga-gpu-scheduling-paas
  - In 1.37, **Extended Resource support and Device Taints went GA**. Pods can ask for `nvidia.com/gpu` and have a DRA driver serve the request. https://kubernetes.io/blog/2026/09/03/kubernetes-v1-37-dra-updates/
  - NVIDIA says some features of its DRA driver are still alpha, and it needs driver 580 or later. https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/dra-intro-install.html
  - NVIDIA donated the DRA driver to the CNCF in March 2026.
  - Talos's own DRA page still calls DRA "beta". https://docs.siderolabs.com/kubernetes-guides/advanced-guides/dynamic-resource-allocation
  - For one GPU, DRA adds moving parts and gives you nothing yet.
- **Ways to share one GPU:**
  - **Time-slicing** works on any card but gives no memory isolation.
  - **MPS** is experimental in the device plugin.
  - **MIG** only exists on datacenter cards (A100, H100, L40S, RTX PRO 6000 and similar), not consumer RTX. https://github.com/nvidia/k8s-device-plugin and https://pkhamdee.blog/2026/06/17/gpu-sharing-on-kubernetes-time-slicing-mig-and-mps-compared-for-llm-workloads/
- **Why not Proxmox passthrough.** It works: q35 machine type, OVMF firmware, `hostpci0 pcie=1`. https://pve.proxmox.com/wiki/PCI_Passthrough
  - OVMF's default 32 GB space for PCI devices (the 64-bit MMIO window) is too small for cards with 24 GB or more of VRAM, so you have to raise it. https://oneuptime.com/blog/post/2026-03-03-configure-gpu-pass-through-for-talos-linux-vms/view **[secondary source]**
  - Passthrough also adds problems with IOMMU groups and resetting the GPU.
  - It makes waking the machine a two-step job: power on the host, then start the VM.
  - Bare metal gives you native performance and a single power switch (IPMI or WoL). Only use Proxmox if the server also needs to run other VMs.
- **AMD.** Use the `siderolabs/amdgpu` extension plus the ROCm GPU Operator with `driver.enable=false`. AMD GPU Operator v1.5.0 (2026-07-28) adds DRA support. https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/hardware-and-drivers/amd-gpu and https://rocm.blogs.amd.com/software-tools-optimization/gpu-operator-1.5.0/README.html
- **Intel.** Use the i915/xe extensions plus the Intel device plugin. On Talos, i915 is built into the kernel, so NFD's `kernel.loadedmodule` rule never fires and you must label the node by hand. https://github.com/intel/intel-device-plugins-for-kubernetes/issues/1688

**Maturity:** Extensions and device plugin are mature. DRA is GA as an API, but NVIDIA's driver is still maturing.

**Talos caveats:**
- The extension versions are tied to the Talos release, so every Talos upgrade means a new Image Factory schematic. Keep a separate GPU schematic.
- The `KernelModuleConfig` format belongs to 1.14.

**Effort:** About 1 day.

## 2. Batch and queueing

**Recommendation:**
- **Keep Kueue** as the only admission layer, and add **JobSet** only if you need multi-pod jobs.
- **Argo Workflows** handles DAGs and cron. It is already wired to a LocalQueue in `kubernetes/platform/two-worker/kueue.yaml`.
- Add **KubeRay** only if you actually use Ray.
- **Skip Volcano.**

**Why:**
- **Kueue v0.19.5** (2026-09-17) is current. v0.20.0-rc.0 makes **v1beta2 the main API and stops serving v1beta1**. https://github.com/kubernetes-sigs/kueue/releases
  - Your manifests use `kueue.x-k8s.io/v1beta1`. Migrate them before upgrading to 0.20. **[the RC detail is unverified until the GA release]**
- Kueue already covers Job, JobSet, RayJob/RayCluster/RayService, LeaderWorkerSet, plain Pods, Deployments and StatefulSets. It also has cohorts, fair sharing, preemption, WorkloadPriorityClass, TAS (beta, on by default since 0.14) and ProvisioningRequest admission checks. https://kueue.sigs.k8s.io/docs/overview/
- **MultiKueue and TAS are irrelevant at this size.** Use ResourceFlavors per node class (`gpu`, `primary`, `secondary`) and one cohort, so the CPU queues can borrow unused quota.
- **Kubernetes 1.37 now has native gang scheduling.** The Workload and PodGroup APIs are beta behind the `GenericWorkload` gate, and 1.37 removed the v1alpha2 PodGroup API. https://www.fairwinds.com/blog/kubernetes-1.37-is-here-pod-rightsizing-dra-and-gang-scheduling
  - For a single-GPU node you don't need it. Kueue's all-or-nothing admission is enough.
- **Volcano** (v1.14, January 2026) replaces the scheduler. That is too much for three nodes. https://volcano.sh/blog/volcano-1.14.0-release/
- **KubeRay.** v1.6 with Kueue 0.17 or later manages RayService as a top-level workload. https://www.anyscale.com/blog/kuberay-v1-7
- **JobSet** is at v0.12. https://github.com/kubernetes-sigs/jobset/releases

**Effort:** Low, since Kueue is already in place. About half a day for flavors, priorities and the API migration.

## 3. Scale-to-zero and on-demand, including waking hardware

**Recommendation:**
- Use **KEDA** (already planned at 2.20.1) for queue-driven ScaledJobs and ScaledObjects.
- Use the **KEDA HTTP add-on** only for light HTTP apps.
- **Skip Knative** unless you adopt KServe's Knative mode.
- For waking physical machines, write a **small custom "power controller"**. No upstream project handles resuming existing nodes.

**Why:**
- **KEDA HTTP add-on.** The README still says "beta, v1.0 planned". https://github.com/kedacore/http-add-on
  - v0.15 added HTTP/2, gRPC and placeholder responses during cold starts.
  - v0.16 (September 2026) added a limit on requests held during a cold start and cold-start duration metrics. https://github.com/kedacore/http-add-on/releases
  - It fits apps with cold starts of a few seconds. It is a poor fit for multi-minute LLM or node-wake cold starts, because clients will time out.
- **Knative Serving** v1.21 (2026-01-27) is mature, but it brings its own networking layer and autoscaler. https://knative.dev/blog/releases/announcing-knative-v1-21-release/
- **Waking nodes.**
  - Cluster Autoscaler only supports WoL through a long-open issue. https://github.com/kubernetes/autoscaler/issues/3614
  - Existing Proxmox autoscalers (kproximate, KubeNodeSmith, CAPMOX with CA) **create and destroy** VMs rather than resuming them. https://github.com/jedrw/kproximate, https://erikparawell.com/kubenodesmith.html
  - Two realistic options:
    - **(a) Custom Kueue AdmissionCheck controller (preferred).** Put the GPU ResourceFlavor behind an AdmissionCheck. When a workload reserves quota, the controller wakes the node, then marks the check Ready once `Node.Ready=True`. After N idle minutes with no admitted workloads, it cordons, drains and powers the node off. Kueue supports user-written checks, though documentation for writing one is thin. https://kueue.sigs.k8s.io/docs/concepts/admission/ and https://github.com/kubernetes-sigs/kueue/discussions/2699
    - **(b) A Cluster Autoscaler `externalgrpc` provider** that maps each node group to power state. https://www.vshn.ch/en/blog/writing-a-kubernetes-cluster-autoscaler-provider-with-externalgrpc/
  - Option (a) is less code. It also fits how Kueue works: quota is counted independently of the nodes that exist, so an admitted workload is a clean wake signal.
- **Power actions:**
  - Proxmox API `POST /nodes/{n}/qemu/{vmid}/status/start` for VMs.
  - IPMI (`chassis power on`) or WoL for bare metal.
  - `talosctl shutdown` or `qm shutdown` (via the guest agent) to power down.
- **Before sleeping a node**, cordon it and taint it with `NoSchedule`. Otherwise it shows as NotReady, and pods are evicted after about 300 s through the default taint-based tolerations.
- **Realistic cold-start budget:**

| Step | Time | Source |
|---|---|---|
| Server firmware boot (POST) | 1–5 min for server boards with RAID controllers | **[estimate, unverified]** |
| Talos boot and node join | about 2 min boot + 1–2 min kubelet registration (3–4 min total) | https://foggyclouds.io/2026-02-11-k8s-talos-autoscaling/ |
| vLLM load and startup | 30–100 s reload for common models; up to about 460 s unoptimized for large ones | https://vllm.ai/blog/2025-10-26-sleep-mode, https://logeshumapathi.com/blog/2026/05/17/vllm-serverless.html |

  - Expect **5–10 minutes from sleep to first token.** That is fine for scheduled or batch work. For interactive use, keep the GPU node on during usage hours.

**Maturity:** KEDA core is mature. The HTTP add-on is beta. The wake controller is DIY.

**Effort:** 2–4 days for the controller, including idle and hysteresis logic.

## 4. Inference serving

**Recommendation:**
- Run **vLLM as a plain Deployment** for persistent single-model serving.
- Or use **Ollama** (or LocalAI) if you want many small models swapped on demand. vLLM's sleep mode also gives sub-second model switching.
- Deliver model weights as **OCI image volumes**.
- **Defer** KServe, llm-d, Dynamo and the Gateway API Inference Extension (GIE) until you have more than one GPU.

**Why:**
- **Image volumes (KEP-4639) went GA in 1.36.** You can mount an OCI artifact containing the weights with no init container. https://bex.co/blog/2026/07/11/kubernetes-136-oci-volumesource-build-artifacts
  - With the weights cached on the node, adding a warm replica took 11.7 s versus 40.7 min re-downloading from object storage. https://arxiv.org/abs/2607.16596
  - KServe's ModelCar feature is officially a stopgap until image volumes. https://kserve.github.io/website/docs/model-serving/storage/providers/oci
  - This also works with your ECR plus IAM Roles Anywhere pull path.
- **KServe v0.17** makes LLMInferenceService production-ready, built on llm-d, with Gateway API and Envoy AI Gateway. That is heavy for one GPU. https://kserve.github.io/website/blog/kserve-0.17-release
- **llm-d** v0.5 to v0.7 targets multi-GPU routing aware of the KV cache and splitting prefill from decode. v0.5 did add scale-to-zero. https://llm-d.ai/blog/llm-d-v0.5-sustaining-performance-at-scale
- **NVIDIA Dynamo** 1.x is a datacenter-scale framework. https://docs.nvidia.com/dynamo/reference/releases/v1-0-0
- **GIE's InferencePool is GA (v1).** Istio, which you already run, is one of the implementations. It's worth adding once you have several replicas or models. https://github.com/kubernetes-sigs/gateway-api-inference-extension

**Effort:** About 1 day for vLLM plus image volumes. KServe or llm-d would take a week or more to run well.

## 5. Latency and performance isolation

**Recommendation:**
- Keep latency-sensitive apps on the CPU workers.
- Taint the GPU node (`homelab/accelerator=nvidia:NoSchedule`).
- Use **PriorityClasses**: latency apps > inference > batch. Map these to Kueue WorkloadPriorityClasses so batch jobs can be preempted.
- Turn on the **static CPU manager only where it pays**, most likely the latency-critical worker, with `reservedSystemCPUs` set.

**Why and how:**
- **Talos config.** Set these under `machine.kubelet.extraConfig`:
  - `cpuManagerPolicy: static`
  - `reservedSystemCPUs`
  - `topologyManagerPolicy: single-numa-node` or `best-effort`
  - `memoryManagerPolicy: Static` plus `reservedMemory`
- **Talos caveat:** set the CPU manager policy in `extraConfig`, not `extraArgs`. Talos then wipes the stale `cpu_manager_state` file itself. Using `extraArgs` crashes the kubelet ("policy differs from checkpoint"). https://github.com/siderolabs/talos/discussions/12840 and https://github.com/siderolabs/talos/issues/7504
- Talos 1.14 is moving kubelet settings into multi-document config. Check that `extraConfig` is still where these belong. **[unverified]**
- **Topology manager** matters only on multi-socket (NUMA) servers. It helps keep the GPU and its CPUs on the same socket.
- **Huge pages:** set `vm.nr_hugepages` through `machine.sysctls` or kernel args. The kubelet then advertises `hugepages-2Mi`. **[Talos specifics unverified]** Useful only for DPDK or databases.
- **In-place pod resize went GA in 1.35.** In 1.37, pod-level resource managers are beta and scheduler preemption for resizes is alpha. https://kubernetes.io/blog/2025/12/19/kubernetes-v1-35-in-place-pod-resize-ga
  - This is good for VPA-style rightsizing. It doesn't mix well with static-CPU Guaranteed pods.
- **VM-level jitter matters too.** On Proxmox, pin vCPUs (the `affinity` option), use `cpu: host`, and avoid overcommitting cores on hosts running latency-sensitive workers.

**Effort:** Half a day, plus benchmarking.

## 6. Onboarding different kinds of nodes

**Recommendation:**
- Deploy **Node Feature Discovery (NFD)** plus NVIDIA **GPU Feature Discovery (GFD)**. Both come bundled with GPU Operator, which adds labels like `nvidia.com/gpu.product` and `.memory`.
- Add a few of your **own labels** in the Talos machine config (`machine.nodeLabels`), under your existing `homelab.tfdraw.dev/` prefix:
  - `capacity-class`: `always-on` | `wakeable` | `gpu`
  - `power`: `vm` | `ipmi` | `wol`
  - `latency-tier`
  - `accelerator`
- Have Kueue ResourceFlavors, taints and the wake controller read these labels.

**Why:**
- NFD v0.19 is mature. Its NodeFeatureGroup API is still alpha and off by default, so skip it. https://docs.nvidia.com/topograph/engines/node-feature-discovery/
- Because your own labels live in machine config, they come from Git (declarative) and survive a node rebuild.
- Intel's built-in-module problem (section 1) shows why you should add manual labels where auto-detection falls short.

**Effort:** Half a day.

---

## Suggested order

1. Upgrade to Talos 1.14 / Kubernetes 1.37 and migrate Kueue to v1beta2.
2. Add node labels, NFD and the capacity classes.
3. Bring up the GPU node: bare-metal schematic plus the device plugin with time-slicing.
4. Set up vLLM with image volumes.
5. Write the Kueue AdmissionCheck power controller.
6. Revisit DRA, GIE and KServe when a second GPU arrives.

**Mostly secondary sources (lower confidence):** the OneUptime and bex.co blogs. The v1.14 extension naming I got from Sidero's docs, not the extensions repo. KEDA 2.21's September 2026 date is only an estimate from its roadmap.