## Purpose

Defines which repository automation remains active after Ansible retirement and the safety and compatibility boundaries that make the removal verifiable.

## ADDED Requirements

### Requirement: Ansible is absent from active repository automation
The repository SHALL contain no tracked Ansible implementation, executable Ansible command, Ansible CI job, or active dependency on a removed Ansible path.

#### Scenario: Repository automation is inspected
- **WHEN** tracked files and active commands are searched after the change
- **THEN** no Ansible implementation or executable reference to a deleted Ansible file is present

### Requirement: Legacy ciphertext is retained safely
Before the committed Ansible Vault file is removed, its ciphertext MUST be copied without decryption to a timestamped private directory with mode `0700`, stored with file mode `0600`, and verified against the source with matching SHA-256 digests.

#### Scenario: Vault retirement is audited
- **WHEN** the private retained copy and its source digest are compared
- **THEN** their SHA-256 digests match and their directory and file permissions are `0700` and `0600` respectively

### Requirement: Shell validation remains available
The repository SHALL retain a shell validation workflow covering ShellCheck and Bats, preserving pull-request fork restrictions and the existing server-default runner selection.

#### Scenario: Shell-related input changes
- **WHEN** a shell script, shell test, shell workflow, shared runner setup, shared change detector, or deleted matching path appears in the pull-request diff
- **THEN** the shell validation job is selected and runs the retained ShellCheck and Bats checks

#### Scenario: Documentation-only input changes
- **WHEN** the pull-request diff contains documentation changes only
- **THEN** expensive shell validation steps are not selected

### Requirement: Current management guidance reflects the supported path
Current repository guidance SHALL describe Talos, OpenTofu, and Helm as the server-management path and SHALL state that laptop bootstrap automation is intentionally deferred.

#### Scenario: Operator reads current guidance
- **WHEN** an operator consults the main README or repository guidance
- **THEN** the documents do not direct the operator to run Ansible and clearly identify the supported server-management path and deferred laptop setup

### Requirement: Historical guidance is non-executable
Retained Ubuntu/kubeadm-era documentation SHALL be marked historical and SHALL link removed repository sources to the pre-removal Git revision rather than present retired playbooks as current executable instructions.

#### Scenario: Reader opens retained legacy documentation
- **WHEN** a reader views a document that describes the retired Ansible or kubeadm path
- **THEN** the document visibly identifies its historical status and points source references at the pre-removal revision

### Requirement: Independent operational interfaces remain intact
Standalone server and recovery scripts and their tests MUST remain present and usable after Ansible is removed.

#### Scenario: Repository scope is compared before and after removal
- **WHEN** the tracked standalone server and recovery scripts and tests are inspected
- **THEN** they remain in the repository and are still covered by their existing validation interfaces
