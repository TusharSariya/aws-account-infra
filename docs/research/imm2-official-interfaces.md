# IBM IMM2: documented automation interfaces

Research date: 2026-09-17. Target supplied by the operator: IBM machine type/model
`7914AC1`, IMM2 firmware `8.41`, build `1AOOA2C`, dated `2021-03-03`, management
address `10.0.0.98`. Machine type 7914 belongs to the System x3550 M4 family.
[IBM model documentation](https://www.ibm.com/support/pages/installation-and-service-guide-lenovo-system-x3550-m4-7914)

This note is **documentation research, not a live capability test**. No power,
configuration, firmware, or other server operations were performed for this note.
The broader session's live evidence must be recorded separately. A documented
command is not proof that a particular platform, license, adapter or account can
execute it.

## Interfaces and scope

| Interface | Documented transport | Appropriate automation scope |
|---|---|---|
| IMM2 CLI | Authenticated SSH; legacy Telnet also exists | Hardware queries and management commands. This is a command protocol, not a POSIX shell or JSON API. |
| IPMI 2.0 | Out-of-band network management | Standard hardware-management operations, subject to enabled access and account authority. |
| SNMP | Agent and traps | Polling and event delivery; IMM2 documents v1 and v3 agents. |
| CIM/XML | HTTP 5988 / HTTPS 5989 | Management clients using the supported CIM providers. An open port alone does not establish supported classes/methods. |
| WS-Management | HTTP 5985 / HTTPS 5986 | XML management transport; a separate interface from CIM/XML and REST. |
| Web/remote presence | HTTPS; remote-presence port | Graphical console, virtual media, firmware workflows and configuration UI. |

SSH is normally TCP 22, SNMP agent UDP 161 and traps UDP 162, remote presence TCP
3900, and IPMI/RMCP uses port 623. These are documented defaults, not a finding
that they are enabled on this machine. See the **IMM/IMM2 tables**, rather than
the XCC tables, in [Lenovo's port reference](https://lenovopress.lenovo.com/tips0511-tcpp-ports-xcc-cmm-imm2-management-processors).
IMM2 documents IPMI 2.0, CIM and serial-over-LAN support.
[IMM2 feature matrix](https://lenovopress.lenovo.com/tips0849-imm2-support-on-lenovo-servers)
The CLI is explicitly a subset of the web management surface.
[CLI overview](https://pubs.lenovo.com/imm2/dw1lm_c_ch7_commandlineinterface)
IPMI enablement is configurable.
[IMM2 configuration](https://pubs.lenovo.com/imm2/dw1lm_c_ch3_configuringtheimm)
SNMP has its own prerequisites and configuration, including agent enablement and
trap settings. [SNMP command](https://pubs.lenovo.com/imm2/dw1lm_r_snmpcommand.html)

### Redfish must be established for the exact firmware family

Do not say that *all IMM2 lacks Redfish*: Lenovo's TCOO-family firmware notes
document Redfish additions on supported platforms, with explicit exclusions.
That does **not** establish Redfish support on this older `1AOO`/7914 target.
A previously observed `/redfish/v1/` 404 should be reported as an observation,
not a complete architectural proof. This research did not establish a supported
Redfish contract for the target. [IMM2 4.10 release notes](https://datacentersupport.lenovo.com/is/de/downloads/DS121799)

XCC is a different controller generation with an explicitly documented Redfish
interface; do not copy its endpoints or feature claims into an IMM2 MCP.
[XCC management interfaces](https://lenovopress.lenovo.com/lp0880-xcc-support-on-thinksystem-servers)

## Safe discovery and CLI constraints

To list the commands available on the actual controller, issue `help` or `?`.
To inspect a command without executing its action, append `-h`, `-help`, or `?`:

```text
help
power -h
reset -h
resetsp -h
spreset -h
```

Use `power state` to read power state. **Never use bare `reset`, `resetsp` or
`spreset` as a discovery probe.** The documented CLI is case-sensitive and uses
text results. Its published output-buffer limit is 2048 characters; output is
returned after completion rather than streaming progress. The target-specific live evidence includes responses longer than 2048 characters, so treat that published limit as cross-platform documentation rather than a measured hard limit here. Discover support
first, use bounded/paged queries where available, and retain raw output beside
parsed fields. [CLI limitations and help syntax](https://pubs.lenovo.com/imm2/dw1lm_c_featuresandlimitations)

## Command families

The [official alphabetical index](https://pubs.lenovo.com/imm2/dw1lm_c_alphabetcommandlist)
is the full **documented** command catalog. The live `help` result should become
the target-specific catalog. The main families and useful examples are:

| Family | Examples | MCP/documentation implications |
|---|---|---|
| Hardware health | `syshealth`, `temps`, `fans`, `volts`, `led` | Expose bounded read operations with units and raw values. |
| Inventory | `vpd`, `adapter`, `storage` | Availability and detail depend on platform and adapters. |
| Events and diagnostics | `readlog`, `ffdc`, `clearlog` | Separate reading from generating/exporting diagnostics and destructive log clearing. |
| Power and boot | `power`, `reset`, `pxeboot`, `fuelg` | Separate state reads, graceful actions, forced actions and power-policy changes. |
| Controller lifecycle | `identify`, `clock`, `info`, `resetsp`, `spreset`, `clearcfg` | Controller restart and factory reset are distinct from host restart. |
| Configuration | `ifconfig`, `ports`, `portcontrol`, `dns`, `ntp`, `users`, `ldap`, `sshcfg`, `ssl`, `tls` | Setters can change access, identity and connectivity. |
| UEFI | `asu` | Discover supported settings; changes require host restart to take effect. |
| Backup and restore | `backup`, `restore`, `restoredefaults` | Configuration export/import and defaults, not host disk/database backup. |
| Serial console | `console`, `srcfg` | Interactive console access, not an ordinary sensor query. |

Sources by family: [monitor commands](https://pubs.lenovo.com/imm2/dw1lm_c_monitorcommands),
[power commands](https://pubs.lenovo.com/imm2/dw1lm_r_serverpowerandrestartcontrolcommands),
[controller commands](https://pubs.lenovo.com/imm2/dw1lm_c_immcontrolcommands),
[configuration commands](https://pubs.lenovo.com/imm2/dw1lm_c_configurationcommands).

`vpd` can retrieve component identity and firmware information.
[VPD reference](https://pubs.lenovo.com/imm2/dw1lm_r_vpdcommand)
`ffdc` supports generating, checking and transferring service data; treat its
export as a separate operation with an explicit destination.
[FFDC reference](https://pubs.lenovo.com/imm2/nn1ia_r_ffdccommand)
Storage inventory/configuration is conditional on controller access and platform
support; do not promise RAID changes or complete disk visibility on this box.
[Storage reference](https://pubs.lenovo.com/imm2/nn1iv_r_storagecommand)

## Exact host power semantics

These are documented commands, **not commands executed during research**.

| Command | Meaning |
|---|---|
| `power state` | Read current host power/system state. |
| `power on` | Turn host power on. |
| `power off -s` | Shut down the OS before switching host power off. |
| `power off` | Switch host power off without the documented OS-shutdown option. |
| `power cycle -s` | Shut down the OS, then switch power off and back on. |
| `power cycle` | Switch power off and on without requesting OS shutdown first. |
| `reset -s` | Shut down the OS before resetting the host. |
| `reset` | Reset the host without the documented OS-shutdown option. |
| `reset -nmi` | Send a non-maskable interrupt; this is a diagnostic action, not a normal restart. |

The `power` command also supports scheduled actions and power-restore policy;
sleep/resume is only available on some servers. These functions require the
corresponding remote power authority.
[Power reference](https://pubs.lenovo.com/imm2/aj1camst04)
Reset can be delayed by 0–120 seconds.
[Reset reference](https://pubs.lenovo.com/imm2/aj1camst05)

Graceful mode expresses the IMM's request to the OS. Do not report a successful
shutdown until a follow-up state query confirms it; orchestration should not
silently fall back to forced power-off. This is an implementation recommendation,
not an additional vendor guarantee. Power actions affect the physical host and
all its VMs and workloads. `resetsp`/`spreset` restart the management controller.
[Controller commands](https://pubs.lenovo.com/imm2/dw1lm_c_immcontrolcommands)

## UEFI, firmware, console and licensing boundaries

The embedded `asu` interface supports showing values, discovering allowed values,
setting options and applying transactions. Safe discovery includes `asu --help`,
`asu show <setting>` and `asu showvalues <setting>`. UEFI changes take effect after
a host reboot. [ASU reference](https://pubs.lenovo.com/imm2/nn1ia_r_asucommand)

The documented configuration backup command exports to TFTP/SFTP and accepts a
passphrase to encrypt passwords inside the exported file. An export can contain
sensitive settings; store it separately from public capability documentation.
[Backup reference](https://pubs.lenovo.com/imm2/dw1lm_r_backupcommand)

Serial over LAN is distinct from graphical KVM: IMM2 documentation assigns COM1
to IPMI SOL. It requires compatible host/UEFI console configuration.
[Serial port settings](https://pubs.lenovo.com/imm2/NN1ia_c_serialportsettings)

System x3550 M4 offers a Features-on-Demand remote-presence upgrade, including
graphics, keyboard/mouse and virtual media. The installed entitlement must be
queried rather than assumed. [x3550 M4 product guide](https://lenovopress.lenovo.com/lp0038-system-x3550-m4-e5-2600)
The generic IMM2 guide describes remote console/media via the web interface;
it is not evidence for a public, stable REST endpoint. Virtual media maps client
devices or images, only one session can use the remote disk at a time, and video
is limited to the integrated graphics path.
[Remote presence](https://pubs.lenovo.com/imm2/NN1ia_c_manageremotecontrol)
Java/ActiveX and later HTML5 clients appear in the cross-platform guide; do not
promise HTML5 on the target until verified.
[Remote control clients](https://pubs.lenovo.com/imm2/remote_control)

IMM web firmware workflows cover IMM2, UEFI and DSA images and active/primary/
backup bank information. A future automation adapter needs a supported tool and
matching machine/firmware package, not a guessed HTTP upload route.
[Firmware update procedure](https://support.lenovo.com/us/en/solutions/ht511296-how-to-update-firmware-using-integrated-management-module)

## Suggested MCP contract (design recommendation)

Start with explicit typed operations: `get_identity`, `get_health`, `get_sensors`,
`get_power_state`, `get_events`, `get_inventory`, `get_boot_settings` and
`get_capabilities`. Each response should identify transport, command, collection
time, parser version, raw output and whether a field was unsupported or truncated.
Do not offer a generic arbitrary-command escape hatch as the main API.

Implement lifecycle operations separately: `power_on`, `shutdown_gracefully`,
`restart_gracefully`, `force_power_off`, `force_reset`, `set_next_boot_pxe`, and
`restart_controller`. Configuration, account, firmware and RAID writes should be
separate capabilities with explicit scope. Do not assume retries are safe after
a timeout on a state-changing command; query state before deciding to retry.

For each capability record three independent facts: vendor documentation,
availability advertised by this controller's help, and the most recent successful
live test. Choose account authority to match the enabled tools; power/restart, transfer and
remote-presence privileges must be checked separately.
[User authority reference](https://pubs.lenovo.com/imm2/NN1ia_c_useraccounts)

The MCP process needs a network path and power independent of this IBM host to
turn it back on after shutdown. Credentials belong in the runtime secret store,
not the tool schema, source file, example command line or returned transcript.
