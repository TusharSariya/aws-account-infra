# Homelab CA & node identity plan

> [!IMPORTANT]
> Historical record only. This document describes the retired Ubuntu/kubeadm and Ansible path. Its commands are archival examples and must not be run. Removed sources remain available in the [pre-removal repository tree](https://github.com/TusharSariyaOrg/aws-account-infra/tree/9a5f9720e45e3bbcbb5637e7bd27a8c688d53add/ansible). Current server management uses Talos, OpenTofu, and Helm.

How the homelab's private CA works, why it is shaped this way, and how to
reproduce it from nothing. This is the **node identity** trust domain: the one
that gets a node AWS credentials to pull from ECR.

It is a *different, unmergeable* trust domain from the Let's Encrypt server certs
in [`cert-manager.md`](cert-manager.md). See
[`../superpowers/specs/2026-07-16-homelab-pki-design.md`](../superpowers/specs/2026-07-16-homelab-pki-design.md)
for why the two cannot be merged. Short version: Roles Anywhere validates a
client cert against a CA whose **private key you hold**. Let's Encrypt never
gives you a signing key, so it structurally cannot serve this role — no amount of
configuration changes that.

## What

A self-signed 4096-bit RSA CA (`CN=homelab-ecr-pull-ca`) on the operator's Mac.
AWS IAM Roles Anywhere pins its public certificate as a trust anchor. Each node
holds a 2048-bit client cert signed by it, and presents that cert to get
short-lived STS credentials scoped to ECR read.

No static AWS access key exists on any node.

## Why this shape

### The CA key *is* the ECR trust root

Anyone holding `homelab-ca.key` can mint a cert for any CN, present it to the
trust anchor, and receive real AWS credentials for the `homelab-ecr-pull` role.
The CA key is therefore exactly as sensitive as an AWS access key for that role,
and everything below follows from that.

This is also why the CA key is **not** backed up to AWS: the CA is what vends AWS
credentials, so storing it in AWS is circular — a total loss of the laptop would
leave you needing AWS access to recover the thing that grants AWS access. It
backs up to the Ansible vault instead, whose password lives outside both.

### Node private keys never move

The node generates its own key (`openssl_privatekey`, on the node), emits a CSR,
the controller signs the CSR, and only the **public certificate** travels back.
The private key never enters git, the vault, the network, or the controller.

The practical consequence: there is no such thing as restoring a node's identity
from backup. You re-run `node-prepare` and it mints a new one. That is the
intended behaviour, not a gap.

### Blast radius

| Compromised | Attacker gets | Recovery |
|---|---|---|
| A node's `key.pem` | ECR **read** for that node's cert lifetime (365d), scoped to the `homelab-ecr-pull` role | Re-run `node-prepare` for a new key; the old cert stays valid until expiry — there is no CRL (see Known gaps) |
| `homelab-ca.key` | Ability to mint unlimited node identities → ECR read, indefinitely | Mint a new CA, replace the trust anchor, re-run `node-prepare` on every node |
| The Ansible vault password | The CA key (it is backed up there), plus every other secret | As above, plus rotate everything in `vault.yml` |

The ceiling on all three is ECR **read** on one repo namespace. The role carries
no write, no delete, no other service. That bound is the main reason this design
is acceptable for a homelab at all.

## Current state (verified 2026-07-16)

| Thing | Value |
|---|---|
| CA subject | `CN=homelab-ecr-pull-ca` (self-signed) |
| CA key | RSA 4096, `~/.config/aws-account-infra/homelab-ca.key`, mode `0600` |
| CA cert | `~/.config/aws-account-infra/homelab-ca.crt`, valid to **2036-07-09** |
| CA SHA1 | `6D:B4:E6:25:75:54:FF:47:E2:46:A3:3F:B5:A9:C3:48:7A:9A:B2:35` |
| CA extensions | `CA:TRUE, pathlen:0` (critical), `Certificate Sign, CRL Sign` (critical) |
| CA key backup | `vault_homelab_ca_key` in `inventories/local/group_vars/all/vault.yml` |
| Trust anchor | `arn:aws:rolesanywhere:us-east-1:992382747916:trust-anchor/09ee21e8-64a3-40c6-9f5e-dcc9c4dcbe59` |
| Profile | `arn:aws:rolesanywhere:us-east-1:992382747916:profile/6308316c-9dfd-401e-bf98-5c209a2149ca` |
| Role | `arn:aws:iam::992382747916:role/homelab/homelab-ecr-pull` |
| Node key | RSA 2048, on-node at `/etc/kubernetes/rolesanywhere/key.pem`, mode `0600`, dir `0700 root` |
| Node cert | 365d, signed by the CA on the controller |
| Signed-cert copies | `~/.config/aws-account-infra/node-certs/<host>.crt` (public only) |

The trust anchor's certificate bundle is byte-identical to the local
`homelab-ca.crt`, and the local `homelab-ca.key` matches that certificate. Both
were verified by fingerprint/modulus comparison, not assumed.

## Node certificates need three extensions

**This is the single most expensive thing to rediscover.** Roles Anywhere
requires an end-entity cert to carry:

```
basicConstraints = critical, CA:FALSE
keyUsage         = critical, digitalSignature
extendedKeyUsage = clientAuth
```

A cert missing them is rejected with:

```
AccessDeniedException: Untrusted certificate. Insufficient certificate
```

That error names *trust*, so it sends you to inspect the CA, the trust anchor,
and the chain — all of which are fine. The cert simply lacks `clientAuth`. Both
failure and fix were verified against the live trust anchor on 2026-07-16.

The extensions are requested in the **CSR** (`openssl_csr` in the
`kubernetes_node` role), because `x509_certificate`'s `ownca` provider carries
the CSR's extensions onto the signed certificate. Requesting them at signing time
instead would not work.

## Reproducing from nothing

### 1. Mint the CA

```bash
mkdir -p ~/.config/aws-account-infra && chmod 700 ~/.config/aws-account-infra
cd ~/.config/aws-account-infra

openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout homelab-ca.key -out homelab-ca.crt \
  -days 3650 -subj "/CN=homelab-ecr-pull-ca" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

chmod 600 homelab-ca.key
```

Keep it **outside the repo checkout**. Inside, a `git clean -x` destroys the ECR
trust root, and only `.gitignore` stands between the key and a `git add -A`.

### 2. Register it with AWS

The trust anchor, profile, and IAM role are Terraform, in
`modules/aws/account_identity/ecr_pull_iam.tf`. The CA's **public** certificate is not a
secret, and lives inline in `config/environments/aws/staging/account.tfvars` as
`homelab_ca_certificate_pem`. Replacing the CA means replacing that PEM.

```bash
cd live/aws/staging/account
tofu apply -var-file="$(git rev-parse --show-toplevel)/config/environments/aws/staging/account.tfvars"
```

The whole chain is `count`-gated on that variable being non-empty
(`local.enable_ecr_pull`), so the plan-only CI job — which has no CA — plans zero of
these resources rather than shipping a null trust anchor and failing at apply with a
cryptic ValidationException.

That gate cuts both ways: an apply that omits the var-file evaluates the gate to
false and plans the live trust anchor, role, and profile for **destruction**,
breaking ECR pull on every node. CI always passes `-var-file` (see `tofu-apply.yml`),
so the automated path is safe; the exposure is a hand-run `tofu apply` in this
directory. `account.tfvars` is not an auto-loaded filename — only `terraform.tfvars`
and `*.auto.tfvars` are — so the flag is never optional.

Record the three outputs: `ecr_pull_trust_anchor_arn`, `ecr_pull_profile_arn`,
`ecr_pull_role_arn`.

The ECR-read policy is attached to the **role**, not a user, and scoped to the
harvest repositories. That scoping is what caps the blast radius in the table above,
so keep it narrow.

### 3. Back the CA key up

```bash
make -C ansible vault-edit    # add vault_homelab_ca_key: | <PEM>
```

Verify the round-trip rather than trusting it — compare the public key of the
vaulted copy against the on-disk key:

```bash
diff <(make -C ansible vault-view | sed -n '/vault_homelab_ca_key/,$p' | tail -n +2 \
        | sed 's/^  //' | openssl pkey -pubout) \
     <(openssl pkey -in ~/.config/aws-account-infra/homelab-ca.key -pubout) \
  && echo "backup verified"
```

### 4. Wire the inventory

In `inventories/local/group_vars/all/main.yml`:

```yaml
kubernetes_node_ecr_rolesanywhere_trust_anchor_arn: "arn:aws:rolesanywhere:...:trust-anchor/..."
kubernetes_node_ecr_rolesanywhere_profile_arn:      "arn:aws:rolesanywhere:...:profile/..."
kubernetes_node_ecr_rolesanywhere_role_arn:         "arn:aws:iam::...:role/homelab/homelab-ecr-pull"
kubernetes_node_ecr_ca_certificate_path: "{{ lookup('env', 'HOME') }}/.config/aws-account-infra/homelab-ca.crt"
kubernetes_node_ecr_ca_privatekey_path:  "{{ lookup('env', 'HOME') }}/.config/aws-account-infra/homelab-ca.key"
```

Setting **both** CA paths non-empty is the switch: the role computes
`kubernetes_node_ecr_credential_provider_enabled` from their length. Leave either
empty and every ECR task skips **silently** — no error, no pull identity, and a
later `ImagePullBackOff` that looks like a registry problem.

### 5. Run it

```bash
make -C ansible node-prepare
```

`CHECK=1` does **not** work for this role and never will. `--check` creates
nothing, so the download has no directory to land in, the CSR has no key, and the
signing has no CSR. Forcing it through with `check_mode: false` would make a "dry"
run actually create directories, download binaries, generate a private key, and
sign a certificate — worse than no dry run at all.

## Adding a node

Add it to `kubernetes_nodes` in `inventories/local/hosts.yml`, then
`make -C ansible node-prepare`. The role generates that node's key, CSR, and
signed cert automatically. Nothing to copy by hand, and no shared key between
nodes — this is the property that makes the design scale past one node.

## Renewal

Node certs last 365 days (`kubernetes_node_ecr_client_cert_days`). Re-running
`node-prepare` re-signs. The CA itself expires **2036-07-09**; replacing it means
a new trust anchor and a re-run across every node.

Nothing warns you before either expires — see Known gaps.

## Recovery: lost laptop

1. Restore the repo and the vault password (kept out-of-band, not in git).
2. `make -C ansible vault-view` → write `vault_homelab_ca_key` back to
   `~/.config/aws-account-infra/homelab-ca.key`, mode `0600`.
3. Recover `homelab-ca.crt` from the trust anchor, which stores the PEM verbatim:

   ```bash
   aws rolesanywhere get-trust-anchor --region us-east-1 --trust-anchor-id <id> \
     --query 'trustAnchor.source.sourceData.x509CertificateData' --output text \
     > ~/.config/aws-account-infra/homelab-ca.crt
   ```

   Do **not** re-mint a self-signed cert from the recovered key instead. It would
   carry a new serial and new dates, so it would not be the certificate AWS pinned
   — you would then be maintaining two CA certs that share a key, which is a
   confusing state to debug later. Fetch the exact PEM.
4. `make -C ansible node-prepare` to re-sign nodes as needed.

The trust anchor doubles as an off-site backup of the CA's *public* half, which
is why step 3 works even with nothing else surviving. Only the key needs the
vault.

## Verifying

```bash
# The minted cert carries the three required extensions
openssl x509 -in ~/.config/aws-account-infra/node-certs/<host>.crt -noout -text \
  | sed -n '/X509v3 extensions/,/Signature Algorithm/p'

# It chains to the CA
openssl verify -CAfile ~/.config/aws-account-infra/homelab-ca.crt \
  ~/.config/aws-account-infra/node-certs/<host>.crt

# AWS trusts the same CA we hold (fingerprints must match)
aws rolesanywhere get-trust-anchor --region us-east-1 --trust-anchor-id <id> \
  --query 'trustAnchor.source.sourceData.x509CertificateData' --output text \
  | openssl x509 -noout -fingerprint
openssl x509 -in ~/.config/aws-account-infra/homelab-ca.crt -noout -fingerprint

# End to end: kubelet pulls from ECR with no imagePullSecret
kubectl run ecr-test --rm --restart=Never \
  --image=<account>.dkr.ecr.us-east-1.amazonaws.com/<repo>:<tag> --command -- /bin/true
kubectl events --for pod/ecr-test | grep Pulled
```

The last one is the only test that proves the whole chain: credential provider →
signing helper → Roles Anywhere → CA → ECR.

## Known gaps

- **A hand-run `tofu apply` without `-var-file` destroys the ECR-pull chain.** CI
  always passes it, so the automated path is safe, but nothing stops an operator
  applying that unit directly and silently reaping the trust anchor, role, and
  profile. Renaming `account.tfvars` to `*.auto.tfvars` would make it auto-load and
  close this, at the cost of the plan-only CI job's empty-CA behaviour.
- **No revocation.** There is no CRL and no OCSP. A leaked node key is valid until
  its cert expires. The only true revocation is replacing the CA and trust anchor.
  Acceptable only because the role is ECR-read-scoped.
- **No expiry monitoring.** Nothing alerts before a node cert (365d) or the CA
  (2036) expires. The failure mode is `ImagePullBackOff` at an arbitrary future
  date, with a cause that will not be obvious.
- **The CA has no serial-number database**, only `homelab-ca.srl`. Lose it and
  `openssl` may reissue a duplicate serial. The Ansible `ownca` path does not use
  it, so this only affects manual signing.
- **Single-operator custody.** One key, one laptop, one vault password. No
  quorum, no HSM, no offline root. Appropriate at this scale; revisit before this
  CA guards anything beyond ECR read.

## Rollback

Disable the identity without deleting anything: blank both CA paths in the
inventory and re-run `node-prepare`. The gate goes false and the ECR tasks stop.
Existing on-node material is left in place, so this is reversible.

To remove it fully:

```bash
# On each node
sudo rm -rf /etc/kubernetes/rolesanywhere /etc/kubernetes/image-credential-provider
sudo rm -f /etc/kubernetes/credential-provider-config.yaml /usr/local/bin/aws_signing_helper
sudo systemctl restart kubelet

# In AWS — profile first; the trust anchor cannot be deleted while in use.
aws rolesanywhere delete-profile      --region us-east-1 --profile-id <id>
aws rolesanywhere delete-trust-anchor --region us-east-1 --trust-anchor-id <id>
```

Nodes then have no ECR credentials, and any ECR-sourced pod stops being able to
pull on its next image fetch.
