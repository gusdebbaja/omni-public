# OpenTelemetry Collector Ansible Project

This Ansible project manages the OpenTelemetry Collector Contrib on Windows and Linux (RedHat and Ubuntu) hosts. It provides a complete set of playbooks for installation, configuration, validation, deployment, upgrade, and uninstallation.

## Project Structure
```plaintext
ansible/
├── inventory/
│   └── hosts.yml
├── group_vars/
│   ├── all/
│   │   └── all.yml
│   └── sandbox/
│       └── all.yml
├── roles/
│   ├── common/
│   ├── linux_install/
│   ├── windows_install/
│   ├── validation/
│   ├── deployment/
│   ├── uninstall/
│   └── upgrade/
└── playbooks/
├── validation_playbook.yml
├── install_playbook.yml
├── deployment_playbook.yml
├── uninstall_playbook.yml
└── upgrade_playbook.yml
```


## Features

- Cross-platform support (Windows, RedHat, Ubuntu)
- Modular design with separate roles for different functionalities
- Comprehensive validation of installation and configuration
- Debug mode for detailed logging and metrics collection
- Flexible configuration via variables
- Support for multiple exporters (Grafana Cloud, Splunk, Prometheus)

## Playbooks

1. **validation_playbook.yml**: Checks if OpenTelemetry Collector is deployed and validates its configuration.
2. **install_playbook.yml**: Installs OpenTelemetry Collector if not already installed.
3. **deployment_playbook.yml**: Deploys configuration to an existing OpenTelemetry Collector installation.
4. **uninstall_playbook.yml**: Uninstalls OpenTelemetry Collector from target hosts.
5. **upgrade_playbook.yml**: Upgrades OpenTelemetry Collector to a specified version.

## Configuration Variables

The project uses variables defined in `group_vars/all/all.yml` and `group_vars/sandbox/all.yml`:

```yaml
# Example variables
otelcol_contrib_version: 0.121.0
monitor_vm_infra_metrics:
  - cpu
  - memory: null
  - disk:
    - /
    - /var
    - /var/log
  - process:
    - name:
      - ansible:
        - enable_logging: true
        - add_labels:
          - my_custom_label: my_custom_label_value
      - remove_labels:
        - k8s.namespace_name
        - k8s.pod_name
        - k8s.container_name
      - docker
      - sshd

debug: true

sent_to:
  - grafana_cloud:
    - monitor_vm_infra_metrics
  - splunk_enterprise:
  - prometheus:
    - send_metrics_with_labels:
      - k8s.namespace.name: monitoring


## Usage
### Prerequisites Linux Hosts (RedHat/Ubuntu)
1. Create ansible user:
```bash
# RedHat
sudo useradd -m ansible
echo "ansible:Ansible123" | sudo chpasswd
sudo usermod -aG wheel ansible

# Ubuntu
sudo useradd -m ansible
echo "ansible:Ansible123" | sudo chpasswd
sudo usermod -aG sudo ansible  
```

2. Configure SSH access:
```bash
# Generate SSH key on control node
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

# Copy SSH key to target hosts
ssh-copy-id -i ~/.ssh/id_ed25519.pub ansible@<target-host>

# Configure SSH server (if password auth is disabled)
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

3. Configure sudo access without password:
```bash
echo "ansible ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/ansible
```
Windows Hosts
1. Create ansible user:
```powershell
$Password = ConvertTo-SecureString "Ansible123" -AsPlainText -Force
New-LocalUser -Name "ansible" -Password $Password -FullName "Ansible Automation" -Description "Ansible automation account"
Add-LocalGroupMember -Group "Administrators" -Member "ansible"
```

2. Configure WinRM:
```powershell
# Run from elevated PowerShell
$url = "https://raw.githubusercontent.com/ansible/ansible/devel/examples/scripts/ConfigureRemotingForAnsible.ps1"
$file = "$env:temp\ConfigureRemotingForAnsible.ps1"
(New-Object -TypeName System.Net.WebClient).DownloadFile($url, $file)
powershell.exe -ExecutionPolicy ByPass -File $file -EnableCredSSP -DisableBasicAuth -Verbose
```
### Running Playbooks
1. Validate OpenTelemetry Collector installation:
```bash
ansible-playbook playbooks/validation_playbook.yml
```
2. Install OpenTelemetry Collector:
```bash
ansible-playbook playbooks/install_playbook.yml
 ```

3. Deploy configuration to existing installation:
```bash
ansible-playbook playbooks/deployment_playbook.yml
 ```

4. Upgrade OpenTelemetry Collector:
```bash
ansible-playbook playbooks/upgrade_playbook.yml
 ```

5. Uninstall OpenTelemetry Collector:
```bash
ansible-playbook playbooks/uninstall_playbook.yml
 ```

### Debug Mode
To enable debug mode during deployment:

## SELinux and AppArmor Considerations
### SELinux (RedHat)
The project automatically configures SELinux contexts for OpenTelemetry Collector:

### AppArmor (Ubuntu)
For Ubuntu systems with AppArmor, the project creates an AppArmor profile:

```bash
# Manual configuration if needed
sudo tee /etc/apparmor.d/usr.local.bin.otelcol-contrib <<EOF
#include <tunables/global>

/usr/local/bin/otelcol-contrib {
  #include <abstractions/base>
  #include <abstractions/nameservice>

  /usr/local/bin/otelcol-contrib mr,
  /etc/otelcol-contrib/** r,
  /var/log/otelcol-contrib/** rw,
  /var/log/journal/** r,
  /var/log/** r,
  /proc/** r,
  /sys/** r,
  network tcp,
  network udp,
}
EOF

sudo apparmor_parser -r /etc/apparmor.d/usr.local.bin.otelcol-contrib
 ```
```

One can deploy 2 VMs using the commands below 
``` bash
sudo virt-install --name rhel-vm --ram 2048 --vcpus 2 --disk path=/var/lib/libvirt/images/rhel-vm.qcow2,size=20 --os-type linux --os-variant rhel9 --network bridge=virbr0 --graphics spice --console pty,target_type=serial --cdrom /path/to/iso/rhel-9.5-x86_64-boot.iso

sudo virt-install --name win10-vm --ram 4096 --vcpus 4 --disk path=/var/lib/libvirt/images/win10-vm.qcow2,size=50 --os-type windows --os-variant win10 --network bridge=virbr0 --graphics spice --cdrom /path/to/iso/SERVER_EVAL_x64FRE_en-us.iso
```