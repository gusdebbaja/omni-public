import nmap
import clickhouse_driver
import yaml

# Configuration
CLICKHOUSE_HOST = 'localhost'
CLICKHOUSE_PORT = 9000
CLICKHOUSE_DATABASE = 'network_cmdb'
SCAN_NETWORK = '192.168.1.0/24'  # Replace with your network range
SNMP_COMMUNITIES = ['public']  # Common SNMP v1/v2c community strings
OTEL_CONFIG_PATH = 'otel_snmp_config.yaml'
def scan_network_devices(network_range):
    """Scans the network for active hosts."""
    nm = nmap.PortScanner()
    nm.scan(hosts=network_range, arguments='-sn')
    return nm.all_hosts()


def classify_device(ip_address, nm_scan_results):
    """Attempts to classify a device based on nmap scan results."""
    host_info = nm_scan_results.host(ip_address)
    mac_address = host_info.get('addresses', {}).get('mac')
    host_name = host_info.get('hostnames', [{}])[0].get('name', '')
    open_ports = list(host_info.get('tcp', {}).keys()) + list(host_info.get('udp', {}).keys())
    os_match = host_info.get('osmatch')
    os_name = os_match[0]['name'] if os_match else None
    services = host_info.get('tcp', {}).items() + host_info.get('udp', {}).items()

    device_type = 'unknown'

    if mac_address:
        oui = mac_address[:8].upper().replace(':', '')
        vm_ouis = ['000C29', '005056', '000569', '001C42']
        router_ouis = ['0001FA', '00049F', '0002B9']
        if oui in vm_ouis:
            device_type = 'vm'
        elif oui in router_ouis:
            device_type = 'router'

    if os_name:
        if 'Windows' in os_name:
            device_type = 'server' if 'Server' in os_name else 'workstation'
        elif 'Linux' in os_name:
            device_type = 'server'
        elif 'Mac OS' in os_name:
            device_type = 'workstation'
        elif 'Router' in os_name or 'Firewall' in os_name:
            device_type = 'router'
        elif 'VirtualBox' in os_name or 'VMware' in os_name or 'Hyper-V' in os_name or 'Parallels' in os_name:
            device_type = 'vm'

    if 'vm' in host_name.lower():
        device_type = 'vm'
    elif 'router' in host_name.lower() or 'gw' in host_name.lower():
        device_type = 'router'

    # Further classification based on open ports and services can be added here
    # For example, if port 80 or 443 is open and the service is 'http' or 'https', it might be a web server.

    return device_type, mac_address, host_name, open_ports, os_name, services

def check_snmp(ip_address, communities):
    """Checks if a device supports SNMP and tries to determine the version and community."""
    snmp_info = {'supported': False, 'version': None, 'community': None}
    try:
        for community in communities:
            # Try SNMP v1 and v2c
            for version, api_version in [('v1', 0), ('v2c', 1)]:
                community_data = CommunityData(community, mpModel=api_version)
                iterator = getCmd(
                    SnmpEngine(),
                    community_data,
                    UdpTransportTarget((ip_address, 161)),
                    ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0)),
                    timeout=1,
                    retries=1
                )
                errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

                if not errorIndication and errorStatus == 0 and varBinds:
                    snmp_info['supported'] = True
                    snmp_info['version'] = version
                    snmp_info['community'] = community
                    return snmp_info
                elif errorIndication:
                    pass # Handle errors if needed
                elif errorStatus:
                    pass # Handle errors if needed

    except ImportError:
        print("Error: pysnmp library is not installed. Please install it using 'pip install pysnmp'")
        return snmp_info
    return snmp_info

def create_clickhouse_table(client, database_name):
    """Creates the ClickHouse table if it doesn't exist."""
    client.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    client.execute(f"""
        CREATE TABLE IF NOT EXISTS {database_name}.network_devices (
            ip_address String,
            mac_address Nullable(String),
            host_name String,
            device_type String,
            open_ports Array(UInt16),
            snmp_supported Boolean,
            snmp_version Nullable(String),
            discovery_timestamp DateTime DEFAULT now(),
            os_name Nullable(String),
            services Array(Tuple(UInt16, String))
        ) ENGINE = MergeTree()
        ORDER BY ip_address
    """)
def insert_device_data(client, database_name, device_info):
    """Inserts device information into the ClickHouse table."""
    client.execute(f"""
        INSERT INTO {database_name}.network_devices (ip_address, mac_address, host_name, device_type, open_ports, snmp_supported, snmp_version, os_name, services)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        device_info['ip_address'],
        device_info['mac_address'],
        device_info['host_name'],
        device_info['device_type'],
        list(device_info['open_ports']),
        device_info['snmp']['supported'],
        device_info['snmp']['version'],
        device_info['os_name'],
        [(port, service.get('name', 'unknown')) for port, service in device_info['services']]
    ])
def generate_otel_snmp_config(devices, output_path):
    """Generates the OpenTelemetry Collector SNMP receiver configuration."""
    receivers = {}
    for device in devices:
        if device['snmp']['supported']:
            receiver_name = f'snmp/{device["ip_address"]}'
            receivers[receiver_name] = {
                'endpoint': f'{device["ip_address"]}:161',
                'community': device['snmp']['community'],
            }
            if device['snmp']['version'] == 'v3':
                print(f"Warning: SNMP v3 configuration for {device['ip_address']} needs manual setup.")
                # In a more advanced scenario, you would include SNMP v3 parameters here
                receivers[receiver_name].update({
                    'version': 'v3',
                    # Add necessary v3 parameters like security_level, security_name, etc.
                })
            elif device['snmp']['version'] in ['v1', 'v2c']:
                receivers[receiver_name]['version'] = device['snmp']['version']

    if receivers:
        config = {
            'receivers': receivers
        }
        with open(output_path, 'w') as f:
            yaml.dump(config, f, sort_keys=False)
        print(f"OTel SNMP receiver configuration saved to {output_path}")
    else:
        print("No SNMP-enabled devices found to generate OTel configuration.")
def main():
    """Main function to orchestrate network scanning and data storage."""
    print("Starting network scan...")
    nm = nmap.PortScanner() # Initialize PortScanner here
    nm.scan(hosts=SCAN_NETWORK, arguments='-sn')
    all_hosts = nm.all_hosts()
    print(f"Found {len(all_hosts)} active hosts.")

    devices_data = []

    try:
        client = clickhouse_driver.Client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT) # Connect without specifying the database initially
        client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE}")
        client.execute(f"USE {CLICKHOUSE_DATABASE}") # Explicitly use the database

        create_clickhouse_table(client, CLICKHOUSE_DATABASE)

        for host in all_hosts:
            print(f"\nProcessing host: {host}")
            device_type, mac_address, host_name, open_ports, os_name, services = classify_device(host, nm)
            print(f"  Type: {device_type}, MAC: {mac_address}, Hostname: {host_name}, Open Ports: {open_ports}, OS: {os_name}, Services: {services}")

            snmp_info = check_snmp(host, SNMP_COMMUNITIES)
            print(f"  SNMP Status: {snmp_info}")

            device_data = {
                'ip_address': host,
                'mac_address': mac_address,
                'host_name': host_name,
                'device_type': device_type,
                'open_ports': open_ports,
                'snmp': snmp_info,
                'os_name': os_name,
                'services': services
            }
            print(f"Device Data to Insert: {device_data}")  
            insert_device_data(client, CLICKHOUSE_DATABASE, device_data)
            devices_data.append(device_data)

        print("\nNetwork scan and data storage complete.")
        generate_otel_snmp_config(devices_data, OTEL_CONFIG_PATH)

    except clickhouse_driver.errors.SocketError as e:
        print(f"Error connecting to ClickHouse: {e}")
        print("Make sure ClickHouse is running locally on port 9000.")
    except clickhouse_driver.errors.DatabaseError as e:
        print(f"ClickHouse Database Error: {e}") # Capture specific database errors
    except ImportError as e:
        print(f"Error: {e}")
        print("Please install the required libraries: pip install python-nmap clickhouse-driver pysnmp pyyaml")
    finally:
        if 'client' in locals():
            client.disconnect()

if __name__ == "__main__":
    main()