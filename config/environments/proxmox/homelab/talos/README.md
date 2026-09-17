# Talos machine configuration

`cluster.json` and `patches/` are non-secret reconstruction inputs for the two
Talos VMs. Run from the repository root with Python 3.9 or later. The helper
acquires Talos CLI v1.13.9 for macOS arm64 or Linux amd64 and checks its pinned
SHA-256 on every invocation. The checksums come from the official GitHub release
asset metadata. This checks integrity; Sigstore signature verification and
independent artifact archival remain recovery-foundation work.

For a **new cluster only**, create its secrets once:

```sh
python3 scripts/homelab-talos-config.py init-secrets
```

For an existing cluster, restore its original `talos-secrets.yaml` instead. Keep
it at `~/.config/aws-account-infra/talos/homelab/talos-secrets.yaml`, owned by the
administrator with mode 0600, in a mode-0700 directory. An alternative private
directory can be selected with `--state-dir`. Never initialize new secrets as a
substitute for restoring an existing cluster's identity.

Generate into a new directory:

```sh
python3 scripts/homelab-talos-config.py generate \
  --output "$HOME/.config/aws-account-infra/talos/homelab/generated-new"
```

The helper validates each config using `talosctl validate --mode metal --strict`.
A successful run creates two `*.machineconfig.yaml` files, `talosconfig`, and
private `generation.log`. Failed runs can leave partial output: do not apply
anything from a failed run. Correct the cause and generate into a new directory.
Diagnostics stay private because configuration parsing errors can contain secrets.
The helper refuses existing outputs and secrets, and refuses secret/output paths
inside this repository. `.gitignore` additionally covers the generated filenames.
Never force-add these files or paste their contents into logs or tickets.

Settings:

- Talos v1.13.9, Kubernetes v1.36.3, CNI `none`, kube-proxy retained.
- Kubernetes endpoint `https://10.0.0.231:6443`, advertised only by the control
  plane. This VIP becomes available after etcd bootstrap. Talos administration
  uses the actual control-plane address `10.0.0.220`.
- DHCP on the NIC selected by its reserved MAC; LAN router reservations supply
  `10.0.0.220`, `10.0.0.222`. The gateway is `10.0.0.1`; Proxmox uses `10.0.0.92` directly.
- All install targets `/dev/sda`, corresponding to scsi0 on
  each Talos VM; the worker data disk is scsi1 (/dev/sdb). Verify this mapping in maintenance mode before applying.
- Bootstrap ISOs retain their original pins. The worker installer adds binfmt-misc to gVisor and QEMU guest agent for ARM CI; its dedicated maintenance is documented in `docs/homelab-ci-arm-maintenance.md`. OCI index digests are pinned in
  addition to version tags: the control plane gets QEMU Guest Agent; the shared worker gets
  QEMU Guest Agent plus gVisor.
- Explicit hostnames, trusted control-plane/shared-worker labels, no sandbox registration taint, and
  disabled control-plane scheduling. KubeSpan remains disabled by default.

These are bootstrap configs. Runtime boot, node registration, guest networking,
Cilium, local-path user-volume provisioning, sandbox enforcement and application
storage still require their implementation and acceptance checks. Task 3.4 supplies
persistent cross-file validation. No generation command contacts a node or
installs Talos.

## Recovery

Preserve the original secrets bundle in encrypted independent backup, alongside
reviewed repository inputs and recoverable CLI/ISO/installer artifacts. Restore
the bundle first, then rerun generation. Reusing secrets preserves cluster PKI;
new administrator certificates may have different issue times. Machine-config
regeneration was checked for equality with the same bundle. This does not restore
etcd or application data: retain and test their own backups separately.

The initial local bundle and validated output are in the administrator's private
homelab directory (`two-vm-20260912`). The encrypted AWS bootstrap archive has passed same-Mac download, decryption
and byte comparison. Fresh-environment recovery remains unverified. See
[the recovery entry point](../../../../../docs/plans/homelab-recovery.md).

References:

- [Pinned CLI release](https://github.com/siderolabs/talos/releases/tag/v1.13.9)
- [Configuration patches](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/system-configuration/patching)
- [MAC-selected link aliases](https://docs.siderolabs.com/talos/v1.13/reference/configuration/network/linkaliasconfig)
- [Virtual IP](https://docs.siderolabs.com/talos/v1.13/networking/advanced/vip)

## Cross-file validation

After OpenTofu initialization and generation, run:

```sh
uv run scripts/homelab-config-validate.py \
  --generated-dir "$HOME/.config/aws-account-infra/talos/homelab/two-vm-20260912" \
  --self-test
```

The script pins PyYAML 6.0.3 through uv, reads VM inputs through OpenTofu console,
strictly validates Talos documents and checks capacity, identities, disk targets,
ISO/installer schematics, version pins, scheduling and secret exclusions. Its
self-test proves wrong schematics, OS install on the data disk and RAM drift are
rejected. It does not provision nodes or prove runtime behavior. Old generated
three-node directories are superseded and must not be applied.
