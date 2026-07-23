# tiac-cli : https://github.com/sajtu/tiac-cli.git

Inventory-driven Terraform configuration generator for system administrators.

`inventory/` is the source of truth. `terraform/*.tf` files are generated from
scratch and should not be edited manually.

###################################################
WARNING: 

* Current version is for new environments and for Proxmox Virtual Machine management via Terraform Infrastructure as Code (IaC) only.
* It does not currently account for existing environment and other resources yet.
* tiac-cli will DELETE *.tf files and generate new files from its inventory.
* Anything that is not part of the tiac-cli inventory will not be re-created.
* This is still work in progress. 

* PROVIDED AS-IS, see LICENSE.
###################################################

## Requirements

- Python 3.9 or later
- No third-party Python modules
- Terraform is **not required** on the authoring workstation

## Repo layout:

```text
tiac-cli/
       ├─ bin/
       │  └── install-tiac-cli*
       │  └── tiac-cli*
       ├─ ve_plugins/
       │  └───────── proxmox/
       │             └────── plugin.py
       │             └────── plugin.json
       ├─ LICENSE
       └─ README.md
```

## Target Installed Layout (new install)

```text
tiac-cli/
       ├─ bin/
       │  └── tiac-cli*
       ├─ config/
       │  └───── global.json
       ├─ inventory/
       ├─ template/
       ├─ terraform/
       ├─ ve/
       └─ ve_plugins/
          └───────── proxmox/
                     └────── plugin.py
                     └────── plugin.json

```
NOTE: bin/install-tiac-cli, LICENSE and README.md are not installed to install path.

### tiac-cli inventory is stored in:

```text
tiac-cli/
       └─ inventory/
```

For example, inventory item `103` is stored at:

```text
inventory/000000000/000000000/000000103/config.json
```

A `DELETED` file in that directory marks the record deleted. Deleted IDs remain
reserved and are omitted from generated Terraform.

## Commands

```text
Usage: tiac-cli COMMAND [SUBCOMMAND] [OPTIONS]

Virtual Environments:
  ve add                         Add and verify a new VE
  ve list                        List configured VEs
  ve show VEID                   Show one VE
  ve verify [VEID]               Verify endpoint and credentials
  init-user [VEID]               Add/update current user's VE credentials

Templates:
  template add [--ve VEID]       Add and validate a Proxmox template
  template list                  List template definitions

Inventory:
  add|create|provision|a pve     Add a PVE VM inventory item
  list|l [TYPE] [--all]          List inventory
  show|display|s ID              Show one inventory item
  remove|rm|delete|del ID        Mark an inventory item DELETED

Generation:
  validate                       Validate TIAC-CLI source data for Terraform
  commit --preview               Preview pending additions
  commit                         Reconcile IDs and rebuild terraform/*.tf

Notes:
  - A VE is one independently managed Virtual Environment.
  - VEIDs range from 1 through 9999.
  - PVE VMIDs equal TIAC-CLI inventory IDs.
  - New IDs are greater than every known TIAC-CLI and VE ID.
  - Credentials are stored per user at ~/.tiac_ve<ID>.key.
  - 'commit' generates Terraform; it does not run git commit.
```

`commit` means **generate Terraform files**. It does not run `git commit`.

## Recommended Installation:

Pull/Clone the repo:

```bash
git clone https://github.com/sajtu/tiac-cli.git
cd tiac-cli
./bin/install-tiac-cli </path/to/IAC>
```
NOTE: Depending on where you plan to install tiac-cli to, you may need to invoke with sudo. 

NOTE: </path/to/IAC> is the path to your Terraform IAC you want tiac-cli to manage. For example: ./bin/install-tiac-cli ~/projects/my-terraform-iac

## Example Workflow

The following example demonstrates an end-to-end TIAC-CLI workflow using a Proxmox VE environment.

The hostnames, usernames, IP addresses, and credentials shown below are examples only.

In the example, ~/projects/my-terraform-iac is the locaton where Terraform IAC repo is maintained and tiac-cli is installed there.

### Add a Virtual Environment

First, register a Proxmox Virtual Environment (VE) with TIAC-CLI.

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli ve add

VE label: ve-proxmox-lab
Proxmox management host or FQDN: pve-01.example.internal
Proxmox API port [8006]:
Verify TLS certificate [yes]:
User name (include realm, e.g. user@pve): iac-admin@pve
Token Name: tiac
Token Secret: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Verifying host name, Proxmox API endpoint, and credentials...
Added VE 0001: ve-proxmox-lab
  Type: Proxmox VE
  Endpoint: pve-01.example.internal:8006
  Platform version: 9.2.4
  Credential file: /home/admin/.tiac_ve0001.key
````

### List Configured Virtual Environments

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli ve list

VEID  TYPE        NAME                      ENDPOINT
----------------------------------------------------------------------------
0001  proxmox     ve-proxmox-lab            pve-01.example.internal:8006
```

### Verify a Virtual Environment

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli ve verify 1

VE 0001 verified successfully.
  Resolved addresses: 10.0.0.11
  Nodes: 2
  VMs/containers: 11
```

### Show Virtual Environment Configuration

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli ve show 1

{
  "credential_configured": true,
  "credential_file": "/home/admin/.tiac_ve0001.key",
  "host": "pve-01.example.internal",
  "id": "0001",
  "name": "ve-proxmox-lab",
  "port": 8006,
  "type": "proxmox",
  "verify_tls": true
}
```

### Add a VM Template

Before TIAC-CLI can provision new VMs, at least one valid template must be registered for the VE.

The Proxmox plugin connects to the VE and validates that the specified VMID exists and is a valid Proxmox template.

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli template add

Checking connection to ve-proxmox-lab (pve-01.example.internal:8006)...
Connection and credentials verified.
Template VMID: 107
Validated Proxmox template:
  VMID: 107
  Name: TIAC-TEMPLATE
  Node: pve-02
  OS Type: Linux (l26)
Secondary label or notes []: debian
Added Template VMID 107 to VE 0001: TIAC-TEMPLATE
```

### List Templates

Template information is retrieved live from the VE and compared with the information cached when the template was registered.

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli template list

VEID  VMID       NAME                      OS                    NODE          SECONDARY             STATUS
-----------------------------------------------------------------------------------------------------------------------------
0001  107        TIAC-TEMPLATE             Linux                 pve-02        debian                
```

### Add a VM to TIAC Inventory

New VMs are provisioned from registered templates.

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli add

Checking connection to ve-proxmox-lab (pve-01.example.internal:8006)...
Revalidating Proxmox Template VMID 107...
Template is valid.
VM name: debian-server
Select Proxmox target Node
  1) pve-01 (online)
  2) pve-02 (online)
  Q) Quit/Cancel
Select: 2
Select Proxmox Storage: local-lvm (lvmthin)
Disk size (GiB) [16]: 8
Added pending VM inventory 000000113
  VE: 0001 — ve-proxmox-lab
  VMID: 113
  Name: tf-debian-server
```console

At this point, the VM has been added to the TIAC-CLI inventory as a pending resource. It has not yet been created in Proxmox.

Multiple VMs may be added to the TIAC-CLI inventory before generating the Terraform configuration.


### Validate the TIAC-CLI Configuration

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli validate

TIAC configuration is valid. 4 Terraform files can be generated.
Terraform provider validation remains pending on the deployment host.
```

TIAC-CLI validation checks the inventory and configuration data that can be validated locally. Full Terraform validation requires Terraform and the required providers to be installed and initialized.


### Generate Terraform Configuration

Run `commit` to generate the Terraform configuration from the current TIAC-CLI inventory.

```console
admin@iac-workstation:~/projects/my-terraform-iac$ ./tiac-cli/bin/tiac-cli commit

Pending Terraform additions:
  000000113  VE 0001  tf-debian-server  Template VMID 107
Generated 4 Terraform files in /home/admin/projects/tiac-cli/terraform
  main.tf
  providers.tf
  variables.tf
  versions.tf
```

The generated directory now contains the Terraform configuration:

```
admin@iac-workstation:~/projects/my-terraform-iac$ ls -l terraform/

total 16
-rw-r--r-- 1 admin users 629 Jul 18 00:56 main.tf
-rw-r--r-- 1 admin users 265 Jul 18 00:56 providers.tf
-rw-r--r-- 1 admin users 111 Jul 18 00:56 variables.tf
-rw-r--r-- 1 admin users 228 Jul 18 00:56 versions.tf
```

### Example Generated main.tf

```text
# GENERATED FILE — DO NOT EDIT
# Source: ve/, template/, and inventory/

resource "proxmox_cloned_vm" "tf_debian_server" {
  provider    = proxmox.ve0001
  id          = 113
  node_name   = "pve-02"
  name        = "tf-debian-server"
  description = "Managed by TIAC/Terraform | VEID: 0001 | Inventory ID: 000000113"

  tags = [
    "tiac",
    "terraform",
    "ve-0001",
    "inv-000000113",
  ]

  started = true

  clone = {
    source_vm_id     = 107
    source_node_name = "pve-02"
    full             = true
  }

  disk = {
    scsi0 = {
      datastore_id = "local-lvm"
      size_gb       = 8
      iothread      = true
    }
  }
}
```

## Terraform Deployment Workflow

TIAC-CLI generates Terraform configuration but does not replace the normal Terraform workflow.

### Simple or Standalone Environment

In a small or standalone environment, TIAC-CLI and Terraform may run on the same administrative workstation or Terraform execution host.

After generating the Terraform configuration, an administrator can run the normal Terraform workflow directly:

terraform init
terraform fmt -check
terraform validate
terraform plan
terraform apply


### Team or Enterprise IaC Workflow

In a team environment, each infrastructure administrator may work from an individual Linux workstation with a local clone of the shared Infrastructure-as-Code repository.

A typical workflow may be:

1. Pull the latest version of the IaC repository.
2. Use `tiac-cli/bin/tiac-cli` to add or modify VE definitions, templates, or VM inventory.
3. Run `tiac-cli/bin/tiac-cli validate`.
4. Run `tiac-cli/bin/tiac-cli commit` to regenerate the Terraform configuration.
5. Review the generated Terraform changes locally.
6. Commit the TIAC-CLI inventory and generated Terraform files to a Git branch.
7. Push the branch to the team's Git repository.
8. Submit the changes for code review and merge approval.
9. After approval and merge, the Terraform execution environment retrieves the updated configuration.
10. Terraform runs `init`, `validate`, and `plan`.
11. The Terraform plan is reviewed or approved according to the organization's change-management process.
12. Terraform runs `apply` to reconcile the managed infrastructure with the approved configuration.

The Terraform execution environment may be a dedicated Terraform runner, an administrative host, or a CI/CD automation platform such as Jenkins.

Other automation tools may also participate in the workflow. For example, Ansible may orchestrate deployment tasks or configure operating systems and applications after Terraform provisions the underlying infrastructure.

The exact workflow is organization-specific. TIAC-CLI's role is to provide a consistent, inventory-driven interface for defining managed infrastructure and generating Terraform configuration that can enter the organization's existing IaC review, approval, and deployment process.



