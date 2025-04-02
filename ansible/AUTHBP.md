# Ansible Authentication Best Practices

This document outlines the technical details for setting up secure authentication methods for both Linux (SSH) and Windows (WinRM/PSRP) hosts in your Ansible environment.

## Linux Authentication with SSH Keys

SSH key-based authentication is the recommended approach for Linux systems. It provides superior security, simplifies automation, and eliminates password management challenges.

### Generating SSH Keys

1. **Generate a new SSH key pair**:

   ```bash
   ssh-keygen -t ed25519 -C "ansible-automation@example.com"
   ```

   The above command creates an Ed25519 key, which offers excellent security with smaller key sizes. If you need compatibility with older systems, use RSA with 4096 bits:

   ```bash
   ssh-keygen -t rsa -b 4096 -C "ansible-automation@example.com"
   ```

2. **When prompted, specify a location for the key**:
   
   For a shared automation account:
   ```
   /etc/ansible/keys/ansible_automation
   ```

   For personal use:
   ```
   ~/.ssh/ansible_key
   ```

3. **Set a strong passphrase** (recommended for enhanced security)

   If using the key in automated processes, you can omit the passphrase, but ensure the key file is properly secured.

4. **Deploy the public key to target hosts**:

   ```bash
   ssh-copy-id -i ~/.ssh/ansible_key.pub user@target-host
   ```

   Alternatively, through Ansible for initial setup:

   ```bash
   ansible all -m authorized_key -a "user=deploy key='{{ lookup('file', '~/.ssh/ansible_key.pub') }}' state=present" --ask-pass
   ```

### Configuring Ansible to Use SSH Keys

In your inventory file or group variables:

```yaml
[linux_servers]
server1.example.com
server2.example.com

[linux_servers:vars]
ansible_user=deploy
ansible_ssh_private_key_file=/path/to/ansible_key
ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
```

For keys with passphrases, use `ssh-agent`:

```bash
eval $(ssh-agent)
ssh-add ~/.ssh/ansible_key
ansible-playbook site.yml
```

### SSH Key Rotation and Management

1. **Regular rotation**: Generate new keys every 6-12 months
2. **Revocation process**: Remove old public keys from authorized_keys files
3. **Key inventory**: Maintain documentation of active keys, their purpose, and expiration

## Windows Authentication Options

### PSRP vs WinRM: Technical Comparison

#### PowerShell Remoting Protocol (PSRP)

PSRP is often the recommended choice for modern Windows environments due to several advantages:

- **Native PowerShell Experience**: PSRP is purpose-built for PowerShell and provides a more authentic PowerShell environment
- **Improved Performance**: Generally offers better performance for PowerShell operations than WinRM
- **Enhanced Functionality**: Supports advanced PowerShell features like session options, remote endpoints, and JEA (Just Enough Administration)
- **Better Error Handling**: More consistent error reporting and handling
- **No Python-in-PowerShell Issues**: Avoids the "PowerShell-within-PowerShell" complexity that can occur with WinRM

To use PSRP in Ansible:

```yaml
[windows_servers]
win1.example.com

[windows_servers:vars]
ansible_connection=psrp
ansible_psrp_protocol=https
ansible_psrp_port=5986
```

#### Windows Remote Management (WinRM)

While WinRM is widely used and fully supported in Ansible, it does have some limitations:

- **Shell Environment Complexity**: Ansible's WinRM implementation can sometimes create nested shell environments
- **Performance Overhead**: May be slower for complex PowerShell operations
- **Error Handling Challenges**: Error messages can sometimes be obscured when passing through multiple layers

### Authentication Methods for Windows

For both PSRP and WinRM, these authentication methods are available, listed in order of preference:

#### 1. Certificate Authentication

**Generating and Deploying Certificates**:

1. **Create a Certificate Authority (if one doesn't exist)**:

   ```powershell
   # On a management server
   $cert = New-SelfSignedCertificate -Type Custom -Subject "CN=AnsibleCA" -KeyUsage CertSign -KeySpec Signature -CertStoreLocation "Cert:\CurrentUser\My"
   Export-Certificate -Cert $cert -FilePath C:\certs\AnsibleCA.cer
   ```

2. **Create Client Certificate**:

   ```powershell
   # Create client certificate signed by the CA
   $clientCert = New-SelfSignedCertificate -Type Custom -Subject "CN=AnsibleClient" -DnsName "AnsibleClient" -CertStoreLocation "Cert:\CurrentUser\My" -Signer $cert
   
   # Export both certificate and private key
   Export-PfxCertificate -Cert $clientCert -FilePath C:\certs\ansible_client.pfx -Password (ConvertTo-SecureString -String "Strong-Password-Here" -Force -AsPlainText)
   
   # Convert to PEM format for Ansible (requires OpenSSL)
   openssl pkcs12 -in C:\certs\ansible_client.pfx -out C:\certs\ansible_client.pem -nodes -password pass:"Strong-Password-Here"
   ```

3. **Generate Server Certificate** on each Windows target:

   ```powershell
   # Create a new local user account for Ansible
   $Username = "ansible"
   $Password = ConvertTo-SecureString "YourStrongPassword" -AsPlainText -Force
   New-LocalUser -Name $Username -Password $Password -FullName "Ansible Automation Account" -Description "Service account for Ansible automation" -AccountNeverExpires

   # Add the user to the Remote Management Users group (required for PSRP)
   Add-LocalGroupMember -Group "Remote Management Users" -Member $Username

   # Optionally, add to Administrators if you need elevated privileges for your playbooks
   # Add-LocalGroupMember -Group "Administrators" -Member $Username

   # Verify the user was added to the correct group
   Get-LocalGroupMember -Group "Remote Management Users"

   $serverCert = New-SelfSignedCertificate -CertStoreLocation "Cert:\LocalMachine\My" -DnsName "server.example.com" -FriendlyName "WinRM HTTPS Certificate" -KeyUsage KeyEncipherment,DigitalSignature -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.1")
   ```

4. **Configure WinRM/PSRP to use Certificate**:

   ```powershell
   # Configure the HTTPS listener with the certificate
   $thumbprint = $serverCert.Thumbprint
   winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"server.example.com`";CertificateThumbprint=`"$thumbprint`"}"
   
   # For PSRP, ensure PowerShell remoting is enabled
   Enable-PSRemoting -Force
   ```

5. **Configure Ansible to use Certificate Authentication**:

   ```yaml
   [windows_servers]
   win1.example.com

   [windows_servers:vars]
   # For PSRP
   ansible_connection=psrp
   ansible_psrp_cert_validation=ignore
   ansible_psrp_protocol=https
   ansible_psrp_port=5986
   ansible_psrp_certificate_key_pem=/path/to/ansible_client.pem
   
   # For WinRM (if used instead)
   ansible_connection=winrm
   ansible_winrm_server_cert_validation=ignore
   ansible_port=5986
   ansible_winrm_transport=certificate
   ansible_winrm_cert_pem=/path/to/client_cert.pem
   ansible_winrm_cert_key_pem=/path/to/client_key.pem
   ```

#### 2. Kerberos Authentication

For domain-joined Windows hosts, Kerberos provides a secure single sign-on experience.

1. **Configure Kerberos on Ansible Control Node** (Linux):

   Install required packages:
   ```bash
   # For Debian/Ubuntu
   apt-get install python-dev libkrb5-dev krb5-user
   
   # For RHEL/CentOS
   yum install python-devel krb5-devel krb5-workstation
   
   # Install Kerberos Python package
   pip install pywinrm[kerberos]
   ```

2. **Configure Kerberos configuration file** (`/etc/krb5.conf`):

   ```
   [libdefaults]
       default_realm = EXAMPLE.COM
       dns_lookup_realm = true
       dns_lookup_kdc = true
   
   [realms]
       EXAMPLE.COM = {
           kdc = dc1.example.com
           admin_server = dc1.example.com
       }
   
   [domain_realm]
       .example.com = EXAMPLE.COM
       example.com = EXAMPLE.COM
   ```

3. **Obtain and cache Kerberos ticket**:

   ```bash
   kinit user@EXAMPLE.COM
   ```

4. **Configure Ansible for Kerberos authentication**:

   ```yaml
   [windows_servers]
   win1.example.com
   
   [windows_servers:vars]
   # For PSRP
   ansible_connection=psrp
   ansible_psrp_transport=kerberos
   ansible_psrp_protocol=https
   ansible_psrp_port=5986
   
   # For WinRM (if used instead)
   ansible_connection=winrm
   ansible_winrm_transport=kerberos
   ansible_port=5986
   ```

#### 3. NTLM/CredSSP Authentication

When certificates or Kerberos are not feasible, NTLM provides a simpler (though less secure) alternative:

1. **Configure Windows hosts** to accept NTLM authentication:

   ```powershell
   # Enable WinRM
   Enable-PSRemoting -Force
   
   # Configure HTTPS listener if not already configured
   New-SelfSignedCertificate -DnsName "server.example.com" -CertStoreLocation "Cert:\LocalMachine\My"
   $thumbprint = (Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {$_.Subject -match "server.example.com"}).Thumbprint
   winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"server.example.com`";CertificateThumbprint=`"$thumbprint`"}"
   
   # Allow unencrypted (only in test environments)
   # NOT RECOMMENDED for production
   winrm set winrm/config/service '@{AllowUnencrypted="true"}'
   
   # Configure authentication
   winrm set winrm/config/service/auth '@{Basic="true";Kerberos="true";Negotiate="true";Certificate="true";CredSSP="true"}'
   ```

2. **Configure Ansible for NTLM authentication**:

   ```yaml
   [windows_servers]
   win1.example.com
   
   [windows_servers:vars]
   # For PSRP
   ansible_connection=psrp
   ansible_connection: psrp
   ansible_psrp_transport: ntlm
   ansible_psrp_protocol: https
   ansible_psrp_port: 5986
   ansible_psrp_ignore_proxy: true
   ansible_psrp_verify: false
   ansible_psrp_cert_validation: ignore
   ansible_password: "{{ windows_ansible_password }}"
   ansible_password=SecurePassword123
   
   # For WinRM (if used instead)
   ansible_connection=winrm
   ansible_winrm_transport=ntlm
   ansible_port=5986
   ansible_user=ansible
   ansible_password=SecurePassword123
   ```

## Security Considerations

1. **Vault Your Credentials**: Always use Ansible Vault to secure any passwords or sensitive information
2. **Principle of Least Privilege**: Use service accounts with minimal required permissions
3. **Network Security**: Restrict remote management ports (22, 5985, 5986) to management networks only
4. **Regular Rotation**: Change credentials and certificates according to your security policy
5. **Monitoring**: Enable logging for authentication attempts and review regularly