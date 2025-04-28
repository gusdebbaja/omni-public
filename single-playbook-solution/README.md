# OpenTelemetry Collector Ansible Playbooks

This repository contains Ansible playbooks for managing the OpenTelemetry Collector Contrib on Linux systems (RHEL/CentOS and Debian/Ubuntu). The playbooks provide a secure, robust installation and configuration management solution with error handling and diagnostics.

## Features

- **Secure credential management**: Uses systemd's credential management instead of plaintext secrets
- **Cross-distribution support**: Works on both RPM (RHEL/CentOS) and DEB (Debian/Ubuntu) based systems
- **Robust error handling**: Provides detailed diagnostics when issues occur
- **Configuration validation**: Validates configuration before applying changes
- **Flexible deployment**: Separate playbooks for installation and configuration updates

## Playbooks

### 1. `install-linux.yml`

Installs or reinstalls the OpenTelemetry Collector Contrib with secure credential management.

**Key features:**
- Downloads and installs the appropriate package for the target distribution
- Sets up secure credential management using systemd
- Validates configuration before starting the service
- Provides detailed diagnostics for troubleshooting
- Supports forced reinstallation

### 2. `deploy-config.yml`

Updates the configuration of an existing OpenTelemetry Collector Contrib installation and restarts the service if needed.

**Key features:**
- Continues even if the service is currently in a failed state
- Restarts the service if configuration changed OR if the service is currently failing
- Validates configuration before applying changes
- Provides detailed diagnostics if the service fails to restart
- Can be used to fix a broken configuration that's causing service failures

## Directory Structure

```
.
├── README.md
├── install-linux.yml
├── deploy-config.yml
├── ansible.cfg
├── inventory/
│   └── hosts
├── files/
│   └── otelcol-contrib.yaml.j2
└── group_vars/
    └── all/
        ├── vars.yml
        └── vault.yml
```

## Prerequisites

### On Control Node
- Ansible 2.9 or newer
- SSH access to target hosts
- Sudo privileges on target hosts

### On Target Hosts
- Linux (RHEL/CentOS 7+ or Debian/Ubuntu)
- Python 3.6 or newer
- Systemd

## Usage

### 1. Prepare your environment

1. Clone this repository:
```bash
git clone https://github.com/yourusername/otelcol-ansible.git
cd otelcol-ansible
```

2. Create your inventory file:
```ini
# inventory/hosts
[collectors]
collector1 ansible_host=192.168.1.10
collector2 ansible_host=192.168.1.11

[collectors:vars]
ansible_user=ansible
ansible_become=yes
```

3. Prepare your configuration template:
```bash
mkdir -p files
# Place your otelcol-contrib.yaml.j2 template in the files directory
```

4. Create a vault file for sensitive information (recommended for production):
```bash
mkdir -p group_vars/all
ansible-vault create group_vars/all/vault.yml
```

Add your secrets to the vault file:
```yaml
vault_splunk_token: "your-actual-splunk-token"
vault_api_key: "your-actual-api-key"
```

### 2. Install OpenTelemetry Collector

Run the installation playbook:

```bash
# Basic installation
ansible-playbook install-linux.yml -i inventory/hosts --ask-vault-pass

# With specific target host(s)
ansible-playbook install-linux.yml -i inventory/hosts --limit collector1 --ask-vault-pass

# Force reinstallation (if already installed)
ansible-playbook install-linux.yml -i inventory/hosts --extra-vars "force_reinstall=true" --ask-vault-pass

# With specific OpenTelemetry version
ansible-playbook install-linux.yml -i inventory/hosts --extra-vars "otelcol_contrib_version=0.123.0" --ask-vault-pass

# To a remote host with SSH and sudo passwords
ansible-playbook install-linux.yml -i "192.168.122.162," --user=ansible --ask-pass --become --ask-become-pass --ask-vault-pass

# For testing: Providing credentials directly (insecure, use only for testing)
ansible-playbook install-linux.yml -i "192.168.122.162," --extra-vars "vault_splunk_token=test-token vault_api_key=test-key" --user=ansible --become --ask-become-pass
```

### 3. Update Configuration

After making changes to your `otelcol-contrib.yaml.j2` template, run the deploy-config playbook:

```bash
# Update configuration
ansible-playbook deploy-config.yml -i inventory/hosts --ask-vault-pass

# Update configuration for specific host(s)
ansible-playbook deploy-config.yml -i inventory/hosts --limit collector1 --ask-vault-pass

# To a remote host with SSH and sudo passwords
ansible-playbook deploy-config.yml -i "192.168.122.162," --user=ansible --ask-pass --become --ask-become-pass --ask-vault-pass

# For testing: Providing credentials directly (insecure, use only for testing)
ansible-playbook deploy-config.yml -i "192.168.122.162," --extra-vars "vault_splunk_token=test-token vault_api_key=test-key" --user=ansible --become --ask-become-pass
```

## Configuration Template

Your `otelcol-contrib.yaml.j2` template should reference the secure environment variables:

```yaml
# Example of accessing secure credentials in the configuration
exporters:
  splunk_hec:
    token: "${pass_splunk_token}"
    # other configuration...
  otlp:
    headers:
      api-key: "${pass_api_key}"
    # other configuration...
```

## Troubleshooting

### Service fails to start

If the service fails to start, the playbooks will automatically collect and display diagnostic information including:

- Service status
- Journalctl logs
- Environment file status
- Service capabilities
- Permissions on the credentials directory

**Note:** The `deploy-config.yml` playbook will continue execution even if the service is currently in a failed state. This allows you to fix broken configurations that may be causing the service to fail.

Common issues:
1. **Configuration syntax errors**: Check the validation output
2. **Missing or incorrect template variables**: Ensure all required variables are defined
3. **Incorrect environment variable references**: Use `${pass_splunk_token}` and `${pass_api_key}` (not the vault variables directly)
4. **SELinux or AppArmor restrictions**: May need additional policies
5. **Resource constraints**: Check if the service has enough resources (memory, file descriptors)
6. **Network connectivity issues**: If the service can't reach required endpoints

### Manual Configuration Validation

To manually validate your configuration:

```bash
# Export temporary environment variables for validation
export pass_splunk_token="your-token"
export pass_api_key="your-api-key"

# Validate configuration
otelcol-contrib validate --config=/etc/otelcol-contrib/config.yaml
```

## Customization

### Changing the OpenTelemetry Collector Version

```bash
ansible-playbook install-linux.yml -i inventory/hosts --extra-vars "otelcol_contrib_version=0.123.0" --ask-vault-pass
```

### Using a Different Configuration Template

```bash
ansible-playbook install-linux.yml -i inventory/hosts --extra-vars "otelcol_config_template=files/custom-config.yaml.j2" --ask-vault-pass
```

## Security Considerations

- All sensitive information should be stored in Ansible Vault for production environments
- For testing purposes only, credentials can be passed directly using `--extra-vars`, but this is **not secure** for production use
- Credentials are managed securely using systemd's credential management
- Service runs with minimal privileges
- Configuration file permissions are set to be readable only by the service user

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
