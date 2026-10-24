# Retained-server mains control

The existing Ubuntu laptop coordinator owns workload retirement, Talos shutdown,
Proxmox shutdown, IMM wake and optional Globe Suite switching through SmartThings.
No second controller is installed. Mains control is disabled unless a host has an
explicit `mains` configuration with `mode: automatic`, verified renewable OAuth,
a completed commissioning cycle and matching site evidence. Modes are `disabled`,
`commissioning`, and `automatic`; legacy `enabled` flags remain readable.

## Safety contract

Shutdown is: 300 seconds of observed idle; block admissions; quiesce clients before
databases; confirm database hibernation and pod termination; gracefully shut down
Talos; observe the worker stopped; verify no other guests, users or active Proxmox
tasks; request orderly Proxmox shutdown; observe IMM off continuously for 60 seconds;
then switch each PSU outlet off. Unknown observations reset the off dwell.

Startup is: confirm all outlets on; wait for IMM; request on only if IMM reports off;
wait for Proxmox; start the retained worker if needed; verify storage; restore databases
and dependent applications; reopen admissions and schedules after readiness.

New demand before Talos shutdown cancels retirement. After shutdown commits, let it
finish, then skip mains removal and wake through IMM. Once a cloud write has been
issued, observe its completion before any opposite command. Multi-PSU switching is
sequential with one outstanding command, never an untracked batch.

There is no automatic forced-off, IMM reset, plug cycling or timeout escalation.
The 20-minute recovery deadline blocks the host. `resume` cannot clear unresolved
external writes. Removing mains configuration is not a recovery mechanism: the
shared pending-operation journal continues to inhibit IMM writes.

## Maintenance, including IMM firmware

Use the same coordinator configuration as the service:

```sh
powerctl --config "$config" maintenance-acquire primary --token imm-update-001 --reason 'IMM firmware maintenance'
powerctl --config "$config" status primary
```

**Do not begin maintenance until `protection.holds.imm-update-001.acknowledged` is
true.** Acquisition first requests inhibition; the coordinator acknowledges only
after already-issued actions have settled. If acquisition encounters a busy lock,
retry the command; an error is not acknowledgement. If the coordinator is stopped,
no new maintenance request is acknowledged.

The lock blocks new application shutdown stages, Talos/Proxmox shutdown, plug
changes, and standalone `homelab-power ensure-on`. It persists across crashes and
has no TTL. `pause`, `resume`, and ordinary shutdown cannot override it. Release
only after maintenance, firmware writes and required recovery/reboots have finished:

```sh
powerctl --config "$config" maintenance-release primary --token imm-update-001
```

Wake the required equipment **before** acquiring maintenance protection. A lock
also blocks wake and does not energize an already-off IMM. Existing workload/CI
holds remain separate: they prevent retirement but permit wake. Critical firmware,
IMM and storage maintenance must use the new acknowledged lock, not a timed gateway
hold. Software cannot prevent manual plug buttons, external Globe/IMM actions,
power failure or maintenance performed outside this workflow.

## Discover and configure SmartThings

1. Identify plug models, all PSU cables and electrical ratings. The laptop, control
   plane and required network equipment must have independent supplies. Disable
   competing plug schedules/automations. Do not infer wiring from device names.
2. Link compatible Globe Suite devices to SmartThings. Unsupported models remain
   disabled; evaluate local control next rather than weakening confirmation rules.
3. Provision API authorization for device listing, status/health reads and switch
   commands. For unattended service use renewable OAuth credentials; PATs are only
   for temporary discovery and supervised commissioning. Current service-integration APIs include preview features:
   verify authorization availability for the actual account before commissioning.
4. Store credentials in a private directory under the service-writable journal,
   e.g. `~/.local/share/homelab-capacity/main/smartthings/credentials.json` (directory
   0700, file 0600). This avoids making the entire configuration directory writable.
   Credential fields are `access_token`, absolute Unix `expires_at`, `refresh_token`,
   `client_id`, and `client_secret`. Never commit them. Refresh rotates tokens atomically.
5. Add the following disabled configuration to the private coordinator JSON and
   use `powerctl --config "$config" discover-plugs secondary`. Discovery does not
   switch devices. Copy device/component IDs, not labels, into the verified mapping.

```json
{
  "mains": {
    "secondary": {
      "mode": "disabled",
      "credentials_file": "~/.local/share/homelab-capacity/main/smartthings/credentials.json",
      "outlets": []
    }
  }
}
```

Each outlet entry is `{"device_id":"VERIFIED_ID","component_id":"VERIFIED_COMPONENT"}`.
List every PSU outlet, with no duplicate or shared outlets across servers. A mains
configuration change requires a coordinator restart. Existing configurations with
no `mains` section continue to use graceful shutdown and IMM wake.

## Initial live test with a temporary token

First link Globe Suite to SmartThings and confirm the plugs appear in the same Samsung
account. At <https://account.smartthings.com/tokens>, choose **Generate new token**,
name it `homelab-plug-test`, and grant device read (`r:devices:*`) and execute
(`x:devices:*`) permissions. No Globe Suite password is needed by the coordinator.

After generating a fresh token, run `ssh laptop-dell-studio`, then run this on the
laptop. Input is hidden and is not placed in shell history. The 23-hour local expiry
leaves a margin inside a newly generated PAT's 24-hour lifetime. Do not use this
expiry estimate for an older token.

```sh
python3 - <<'PYTOKEN'
import getpass, json, os, time
from pathlib import Path
os.umask(0o077)
p = Path.home() / ".local/share/homelab-capacity/main/smartthings/credentials.json"
p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if p.exists():
    raise SystemExit("Credentials already exist; preserve them and review before replacing.")
token = getpass.getpass("Fresh SmartThings PAT: ").strip()
if not token:
    raise SystemExit("No token entered; nothing saved.")
with p.open("x") as stream:
    json.dump({"access_token": token, "expires_at": int(time.time()) + 23 * 3600}, stream)
    stream.write("\n")
p.chmod(0o600)
print("Saved privately:", p)
PYTOKEN
```

Tell the operator the file is saved, not the token itself. Begin with read-only
`discover-plugs`; do not infer safe wiring or enable mains control from discovery
alone. This temporary token cannot provide unattended renewable access.

## Commission secondary, then primary

Deploy the updated Proxmox helper on each host **before** the coordinator update;
old helpers have no active-task evidence and therefore block new automatic shutdown.
Deploy the updated package to the existing laptop virtual environment. Preserve
all journals, existing acceptance, credentials and registered identities.

Keep mains disabled during read-only verification. Save actual controlled mapping
evidence in `HOST-mains-mapping.json` with `host`, the exact `outlets` array and an
`evidence` reference. Preserve the existing graceful-shutdown acceptance.

Select `mode: commissioning` for secondary, restart the coordinator, then run:

```sh
powerctl --config "$config" auth-status secondary
powerctl --config "$config" commission-mains secondary
```

A session needs at least two hours of remaining authorization and lasts 90 minutes.
It first wakes and verifies readiness, allows normal 300-second idle retirement,
observes orderly shutdown and mains removal, then automatically requests restoration.
Only verified restored readiness writes `HOST-mains-acceptance.json`, binding the
cycle, shutdown operation, timestamps and outlet IDs. No manually asserted success
flags are accepted. Repeat separately for primary after secondary passes.

Expiry or disabled mode prevents further cuts but permits safe AC restoration.
Unresolved cloud commands and maintenance protection still block conflicting writes.
A completed session grants no continuing permission to remove mains.

For automatic mode, supply renewable OAuth credentials privately and run
`auth-refresh HOST`; `auth-status HOST` reports expiry and refresh verification
without secrets. Credentials include `access_token`, `expires_at`, `client_id`,
`client_secret`, `refresh_token`, and the token endpoint used by the authorization
flow. Only the SmartThings `/oauth/token` and `/v1/oauth/token` endpoints are accepted.
Client registration and account authorization must be completed externally; a PAT
cannot be converted into a refresh token. Refresh begins one hour before expiry,
persists intent before sending, and atomically saves rotated tokens. An uncertain
refresh requires reauthorization rather than replaying a possibly single-use token.

Automatic mode also requires `HOST-mains-site.json` with the exact `outlets` array
and `electrical_rating`, `exclusive_load`, `no_competing_automation`, each containing
an `evidence` reference and `checked_at` timestamp. Record actual inspections, never
placeholder approvals. Keep unattended switching disabled until these and both
cold-cycle validation and renewable authorization are complete.

Read-only acceptance uses an awake hold so probe workloads retain admission.
Mutating maintenance and deployment CI use `--wait --freeze`: wake first, wait for restored readiness, then
request a durable freeze and wait for acknowledgements for every host. Failed or
cancelled work retains its freeze. Release requires `--verified` after checking the
operation completed safely; deleting a Lease does not clear a persisted freeze.

## Diagnosis and rollback

`status` reports lifecycle stage, observation time, mains samples, durable maintenance
locks and pending external command intent. Pending cloud writes include their command
ID when the acknowledgement was received. SmartThings success is not completion:
a matching device event timestamp must be newer than the intent before another
outlet command is allowed. Cloud errors never cause blind write retries.

If acknowledgement is lost, preserve all journals and inspect provider/device evidence.
A still-on outlet does not prove that a queued off was cancelled. Do not remove a
pending record or request the opposite state merely to unblock recovery. A crash
before sending may conservatively require manual investigation as well. An IMM
unreachable error is never treated as proof that it is off.

To roll back new switching, disable mains and restart while preserving journals.
This inhibits new cuts while preserving safe restoration; it cannot cancel a command already delivered to
SmartThings. Resolve any pending command before rollback/recovery can safely wake
servers. Keep the safety-aware coordinator/IMM adapter installed until recovery is
complete; reverting to old binaries would discard enforcement of the new interlock.

References: [Globe Suite partner listing](https://partners.smartthings.com/partners/globe-suite),
[SmartThings commands](https://developer.smartthings.com/docs/service-integrations/control-devices),
[token management](https://developer.smartthings.com/docs/service-integrations/token-management),
[authorization](https://developer.smartthings.com/docs/getting-started/authorization-and-permissions).

## Deploy through CI

Use `retained-power-deploy` on `main`, with confirmation `retained-power`, after
reconciling the management chart using the existing `homelab-ci-admission` apply
workflow. That chart grants the coordinator its namespace-scoped freeze-ack permission.
The deployment job wakes both hosts, waits for acknowledged CI freezes, transfers
checksummed reviewed Python sources, updates both fixed Proxmox helpers, and verifies
all installed hashes before releasing the freeze. No config, token or journal is
replaced. A failed deployment retains the freeze for inspection.

The laptop stores the exact revision and source hashes in
`~/.local/share/homelab-capacity/deployed.json`; previous sources are retained under
`releases/REVISION-SUFFIX/`. `platform/automatic-power/deploy.py --receive` is the
fixed SSH entry point, installed as `~/.local/share/homelab-capacity/ci-deploy.py`.
The dedicated public key uses `restrict,command="python3 /home/tushar/.local/share/homelab-capacity/ci-deploy.py --receive"` in `authorized_keys`.
Keep its private key in the `prod` environment secret `RETAINED_POWER_DEPLOY_KEY`
and the independently verified laptop host-key line in environment variable
`RETAINED_POWER_KNOWN_HOSTS`. The key cannot open an interactive shell or forward ports.
Bootstrap enrollment is separate from deployments; subsequent runs update the receiver
from the reviewed revision only after successful verification.

The CI network reaches the primary Proxmox subnet router before the laptop. A
second restriction for the same public key on primary permits only
`/usr/bin/nc 10.0.0.181 22`; it relays the end-to-end SSH connection to the laptop
without allowing a root shell or arbitrary forwarding. Pin both host keys in
`RETAINED_POWER_KNOWN_HOSTS`. Both machines must be awake before deployment.

The Ubuntu GPU desktop is temporarily disabled: `desktopQuota: false` and
`desktop.enabled: false` keep its queue at zero quota/Hold and remove its runtime
from the desired Helm manifests. CI's independent bootstrap reconciles those
explicit flags with the accepted node UID, adds the quarantine taint, and scales
any existing desktop runtime to zero. It does not delete model volumes or change
the desktop's OS/power state. Re-enabling requires deliberate configuration changes
and readiness validation before the operator removes quarantine.
