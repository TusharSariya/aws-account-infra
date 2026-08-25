# ServeRAID Health Validation and Monitoring Plan

## Assessment

The eight Seagate ST9300653SS drives have approximately 52,220 power-on hours,
or 5.96 years of powered-on operation. This is evidence of age, not proof that
the drives are failing. Drive reliability figures such as mean time between
failures and annualized failure rate describe populations; they are not
countdowns for individual drives. Seagate makes this distinction in its [drive
reliability guidance](https://www.seagate.com/support/kb/hard-disk-drive-reliability-and-mtbf-afr-174791en/).

The ST9300653SS is an enterprise 300 GB, 15K RPM SAS drive. Seagate specified a
0.44% annualized failure rate under its stated operating conditions, a five-year
warranty, and an operating temperature range of 5 to 55 degrees Celsius. The
observed temperatures of 27 to 28 degrees Celsius are excellent. See the
[Seagate Savvio 15K.3 data
sheet](https://www.seagate.com/www-content/product-content/savvio-fam/enterprise-performance-15k-hdd/savvio-15k-3/en-gb/docs/savvio-15k-3-data-sheet-ds1732-5-1201gb.pdf).

Three drives reported nonzero grown-defect counts:

| MegaRAID device ID | Grown defects |
|---:|---:|
| 51 | 7 |
| 53 | 2 |
| 54 | 1 |

A nonzero grown-defect count does not by itself require replacement. A rising
count, an uncorrectable error, a predictive-failure indication, or a controller
state change is materially stronger evidence. Record a baseline and monitor
changes by drive serial number.

The array should therefore be described as an unverified, higher-risk component
rather than a failed component. Its drives are the same model and age, are
beyond their original warranty period, and share one controller and backplane.
The RAID must not be the only copy of important data.

## Safety rules

- Back up the Proxmox configuration before starting a full-media operation.
- Confirm the actual RAID level, virtual-drive state, cache-protection state,
  and replacement-drive compatibility first.
- Have at least one, preferably two, compatible replacement SAS drives on hand.
- Do not run a patrol read and consistency check at the same time.
- Do not run either operation during a rebuild, initialization, or migration.
- Do not launch parallel SMART long tests across the eight drives.
- Do not use destructive `badblocks`, destructive `fio`, or write-surface tests.
- Do not treat a benchmark as a health test.
- Stop and investigate if the controller resets, the virtual drive degrades, or
  any uncorrectable error appears.

IBM documents that M5110-family controllers can reset during heavy I/O,
including when a virtual-drive consistency check overlaps a drive patrol read.
See the [IBM M5110 reset
advisory](https://www.ibm.com/support/pages/ibm-serveraid-m5110-m5115-and-m5016-sassata-controllers-might-reset-during-heavy-io-ibm-system-x-and-flex-systems).

## Passive baseline

Install a vendor controller utility compatible with the IBM ServeRAID M5110,
preferably StorCLI, using the [IBM ServeRAID M5110 support
matrix](https://www.ibm.com/support/pages/support-matrix-sassata-ii-serveraid-m5110-m5110e-m5120-m1115-m1000-m5014-m5015-m5016-m5025-m5210-m5210e-m5225-mr10i-mr10ie-mr10il-mr10is-mr10k-mr10m-and-megaraid-8408)
to select a supported build. Verify it can identify the controller before
enabling automation.

Capture these read-only controller reports:

```bash
sudo storcli64 /c0 show all
sudo storcli64 /c0/eall/sall show all
sudo storcli64 /c0/vall show all
sudo storcli64 /c0 show events
sudo storcli64 /c0 show patrolread
sudo storcli64 /c0 show cc
sudo storcli64 /c0/bbu show all
sudo storcli64 /c0/cv show all
```

An M5110 may expose either battery-backup or CacheVault information. One of the
last two commands may report that the requested device is unavailable. That is
not itself an error; the controller report must identify which protection
mechanism is installed.

Capture extended SAS SMART information through the MegaRAID device IDs:

```bash
for id in 47 48 49 50 51 53 54 55; do
  sudo smartctl -x -d "megaraid,$id" /dev/sda
done
```

Review relevant kernel history:

```bash
sudo journalctl -k --no-pager |
  grep -iE 'megaraid|medium error|predictive|uncorrect|I/O error|reset|degrad|fault'
```

These queries retrieve existing state and logs. They do not perform a surface
scan and impose negligible drive load.

Record the following by drive serial number:

- Physical-drive and virtual-drive state.
- SMART health status.
- Grown-defect count.
- Media-error, uncorrectable-error, predictive-failure, and non-medium-error
  counts.
- Drive temperature.
- SAS link and PHY error counts where available.
- Controller event history and bad-stripe count.
- Cache-protection health and effective virtual-drive cache policy.
- Patrol-read and consistency-check status and history.

Retain the raw reports alongside a timestamped, normalized counter snapshot.
Counter deltas are more useful than isolated absolute values.

## Controlled deeper validation

### Preconditions

Do not begin active testing until:

- The virtual drive reports `Optimal`.
- Every expected physical drive reports `Online`.
- No rebuild, initialization, patrol read, or consistency check is active.
- The controller event log has been captured.
- Cache protection reports healthy, or write-back caching is disabled.
- An off-host backup exists and has been checked for readability.
- Compatible replacement disks are available.

### Patrol read

Use one controller patrol read as the first full-media test. A patrol read asks
the controller to verify sectors on its physical disks and gives the controller
an opportunity to handle recoverable read problems with knowledge of the RAID
layout.

IBM describes patrol read as an adaptive process that reduces activity during
host I/O. IBM's ServeRAID guidance recommends approximately a 30% patrol-read
rate as a balance between validation and performance. See [IBM patrol-read and
consistency-check guidance](https://www.ibm.com/support/pages/node/858116) and
the [ServeRAID M software user
guide](https://public.dhe.ibm.com/systems/support/system_x_pdf/ibm_serveraid_m_software_user_guide_10th_edition.pdf).

Before starting it, inspect the current configuration:

```bash
sudo storcli64 /c0 show patrolread
```

The exact start and rate-setting commands must be confirmed against the
installed StorCLI version's help before use:

```bash
sudo storcli64 /c0 set patrolread r=30
sudo storcli64 /c0 start patrolread
```

Monitor progress and controller state throughout:

```bash
sudo storcli64 /c0 show patrolread
sudo storcli64 /c0 show
sudo storcli64 /c0/eall/sall show
sudo journalctl -k --since '-10 minutes' --no-pager
```

If the installed version rejects the rate syntax, do not guess or substitute a
different `set` command. Consult its built-in help and the [Broadcom StorCLI
reference](https://docs.broadcom.com/doc/12352476).

After completion, recapture the controller, event, and SMART baselines. Any new
media error, grown defect, uncorrectable error, drive-state change, or controller
reset must be investigated before continuing.

### Consistency check

A consistency check validates virtual-drive parity, so it provides different
coverage from a patrol read. It can impose more controller and disk load and may
repair parity inconsistencies.

Run one consistency check in a separate maintenance window only after the
patrol read has completed cleanly. Confirm that no patrol read or other
background task is active, then use the syntax reported by the installed
StorCLI help. Monitor the controller, kernel log, temperatures, and latency
until it completes.

Do not make a consistency check the first test of an unverified array, and do
not overlap it with patrol read.

### SMART self-tests

Do not schedule routine parallel SMART long tests in addition to controller
patrol reads. They duplicate much of the surface-read workload without the
controller's RAID-level corrective context.

A short SAS SMART self-test may be used to investigate one suspect drive if the
controller and drive report support for it. Run it on one device at a time and
inspect the self-test log afterward:

```bash
sudo smartctl -t short -d megaraid,51 /dev/sda
sudo smartctl -l selftest -d megaraid,51 /dev/sda
```

Do not treat an unsupported self-test command as a disk failure.

## Continuous monitoring design

Use two notification paths:

1. Local Proxmox notification for controller and disk failures.
2. Prometheus and Alertmanager for counter trends, dashboards, and alert
   routing.

The local path remains useful if Kubernetes, Prometheus, or the physical host's
network-facing workloads are unavailable. Proxmox documents its standard SMART
monitoring behavior in the [Proxmox VE administration
guide](https://pve.proxmox.com/pve-docs-8/pve-admin-guide.pdf), but a hardware
RAID controller also requires its vendor utility to observe physical disks and
array state.

### Collector

Implement a root-owned systemd service and timer on Proxmox that:

- Runs every five minutes.
- Queries StorCLI using JSON output where supported.
- Queries SAS SMART telemetry every 30 minutes.
- Keys every metric by stable controller, enclosure, slot, and serial number.
- Writes Prometheus metrics atomically to the node-exporter textfile collector
  directory.
- Retains the most recent raw JSON or text report for troubleshooting.
- Exits nonzero if the controller cannot be queried or the output schema is
  unrecognized.
- Never starts, stops, or changes a controller background operation.

Validate the JSON schema against captured M5110 output before relying on it. If
this StorCLI release does not provide usable JSON, parse a pinned text format
with fixture-based tests rather than loosely matching arbitrary lines.

### Metrics

Export at least:

- Controller health and query success.
- Virtual-drive state.
- Physical-drive state and presence.
- Media-error count.
- Other-error count.
- Predictive-failure count.
- Grown-defect count.
- Drive temperature.
- SAS link-error counters where available.
- Bad-stripe count.
- Patrol-read and consistency-check state.
- Cache-protection state.
- Effective write-cache policy.
- Rebuild state and completion percentage.

### Immediate alerts

Alert immediately when:

- A virtual drive is not `Optimal`.
- A required physical drive is missing or not `Online`.
- SMART health reports failure.
- Predictive-failure count is nonzero.
- A new uncorrectable error appears.
- A new bad-stripe entry appears.
- The array degrades or begins an unexpected rebuild.
- A foreign configuration appears.
- The controller resets or enters a fault state.
- Cache protection is unhealthy while write-back caching remains active.
- The metrics collector cannot query the controller for two consecutive runs.

### Trend alerts

Alert on a counter increase, not merely a nonzero historical value, when:

- Grown defects increase from baseline.
- Media-error or non-medium-error counts increase.
- SAS link or PHY errors repeatedly increase.

Use these temperature thresholds:

- Warning above 45 degrees Celsius.
- Critical at or above 50 degrees Celsius.

The thresholds leave operating margin below Seagate's published 55-degree
maximum. A rapidly rising temperature should alert even before reaching those
values.

## Replacement criteria

Do not replace a drive solely because it has 52,220 hours or a stable nonzero
grown-defect count. Replace or retire a drive when any of these occur:

- The controller reports predictive failure.
- SMART health reports failure.
- An uncorrectable read or write error appears.
- Its grown-defect or media-error count increases from baseline.
- It drops offline, repeatedly resets, or causes rebuilds.
- Its link errors continue increasing after ruling out controller, backplane,
  and cabling problems.
- It cannot complete the controller-managed validation process.
- Its behavior materially diverges from the other drives in the same workload.

Drive 51, with seven existing grown defects, is the first replacement candidate
if its count changes. Drives 53 and 54 receive the same delta-based monitoring.

If errors appear on several drives at once, investigate the controller,
backplane, power, cooling, and firmware before assuming independent disk
failures.

## Cadence

| Activity | Cadence |
|---|---|
| Controller state and event query | Every 5 minutes |
| SAS SMART telemetry | Every 30 minutes |
| Automated counter-delta evaluation | Daily |
| Patrol read | Monthly during low activity |
| Consistency check | Quarterly in a separate maintenance window |
| S3 restore exercise | Quarterly |
| Physical inspection and firmware review | Every 6 months |

Postpone a scheduled patrol read or consistency check when a backup, rebuild,
migration, heavy workload, or other background operation is active.

## Acceptance criteria

The storage is suitable for rebuildable Kubernetes workloads when:

- The RAID level and all controller policies are known and recorded.
- The virtual drive remains Optimal.
- Cache protection is healthy or the effective policy is safely write-through.
- A patrol read completes without new uncorrectable errors or controller reset.
- A later consistency check completes without an unexplained parity error.
- Grown-defect and media-error counters remain stable across the tests.
- Prometheus reports every drive by serial number and physical slot.
- A simulated collector failure reaches both local and Alertmanager notification
  paths.
- A simulated non-Optimal metric fires the critical alert.
- Off-host S3 backup and restore succeeds independently of the RAID.

Passing these checks does not make the array permanent or highly available. It
demonstrates that it is currently usable as monitored, replaceable local
capacity while durable data remains recoverable elsewhere.
