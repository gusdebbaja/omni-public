#!/usr/bin/env python3
"""
Advanced SNMP to OpenTelemetry Config Generator
----------------------------------------------

This script automatically detects SNMP version and generates OpenTelemetry SNMP receiver
configuration, optionally injecting it into an existing OTel Collector config.

Features:
- Auto-detects SNMP version (v1, v2c, v3)
- Identifies device type and appropriate metrics
- Generates full OTel receiver configuration with proper structure
- Can inject the SNMP receiver into an existing collector config
- Adds the receiver to metrics pipeline automatically

Usage:
  python3 snmp-otel-config-generator.py --host 192.168.1.222 [--port 161]
  
  # Use with existing snmpwalk output:
  python3 snmp-otel-config-generator.py --input snmpoutput.txt --host 192.168.1.222
  
  # Inject into existing config:
  python3 snmp-otel-config-generator.py --host 192.168.1.222 --inject-into /etc/otel/config.yaml

Requirements: PyYAML

Author: User
Date: April 2025
"""

import argparse
import copy
import os
import re
import subprocess
import sys
import tempfile
import time
import yaml

def detect_snmp_version(host, port=161, community="public", timeout=2):
    """
    Attempt to detect SNMP version by trying each version in sequence.
    Returns a tuple of (version, credentials) where credentials is a dict with auth info
    """
    print(f"Detecting SNMP version for {host}:{port}...")
    
    # Define versions to try, in order of preference
    versions_to_try = [
        # Version 2c with community string
        {
            "version": "2c",
            "args": ["-v2c", "-c", community],
            "config": {"version": "v2c", "community": community}
        },
        # Version 1 with community string
        {
            "version": "1",
            "args": ["-v1", "-c", community],
            "config": {"version": "v1", "community": community}
        },
        # Version 3 with no auth, no priv
        {
            "version": "3 (noAuthNoPriv)",
            "args": ["-v3", "-l", "noAuthNoPriv", "-u", "public"],
            "config": {"version": "v3", "security_level": "no_auth_no_priv", "user": "public"}
        },
        # Version 3 with auth, no priv (example for testing)
        {
            "version": "3 (authNoPriv)",
            "args": ["-v3", "-l", "authNoPriv", "-u", "otel", "-a", "MD5", "-A", "password"],
            "config": {
                "version": "v3", 
                "security_level": "auth_no_priv",
                "user": "otel",
                "auth_type": "MD5",
                "auth_password": "${env:SNMP_AUTH_PASSWORD}"
            }
        }
        # We omit authPriv here because it requires both passwords
    ]
    
    # Simple OID to test with - system description
    test_oid = "1.3.6.1.2.1.1.1.0"
    
    for version_info in versions_to_try:
        print(f"  Trying SNMP {version_info['version']}...")
        
        try:
            cmd = ["snmpget"] + version_info["args"] + [f"{host}:{port}", test_oid]
            
            # Create a temporary file for stderr
            with tempfile.TemporaryFile() as stderr_file:
                # Run with timeout
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr_file, text=True)
                try:
                    stdout, _ = process.communicate(timeout=timeout)
                    
                    # Check if command was successful
                    if process.returncode == 0 and stdout.strip():
                        print(f"  ✓ Success with SNMP {version_info['version']}")
                        return version_info["config"]
                except subprocess.TimeoutExpired:
                    process.kill()
                    print(f"  ✗ Timeout with SNMP {version_info['version']}")
                    continue
                
                # If we got here, the command failed
                stderr_file.seek(0)
                stderr = stderr_file.read().decode('utf-8')
                print(f"  ✗ Failed with SNMP {version_info['version']}: {stderr[:100]}...")
        
        except Exception as e:
            print(f"  ✗ Error with SNMP {version_info['version']}: {e}")
    
    print("Could not detect SNMP version. Please specify manually.")
    return None

def run_snmpwalk(host, port=161, snmp_config=None, timeout=30):
    """Run snmpwalk with the detected or specified SNMP configuration."""
    if snmp_config is None:
        snmp_config = {"version": "v2c", "community": "public"}
    
    print(f"Running snmpwalk on {host}:{port} with SNMP {snmp_config['version']}...")
    
    # Build command based on SNMP version
    cmd = ["snmpwalk"]
    
    if snmp_config["version"] in ["v1", "v2c"]:
        version = snmp_config["version"].replace("v", "")
        cmd.extend([f"-v{version}", "-c", snmp_config["community"]])
    elif snmp_config["version"] == "v3":
        cmd.append("-v3")
        
        if "security_level" in snmp_config:
            if snmp_config["security_level"] == "no_auth_no_priv":
                cmd.extend(["-l", "noAuthNoPriv", "-u", snmp_config["user"]])
            elif snmp_config["security_level"] == "auth_no_priv":
                cmd.extend([
                    "-l", "authNoPriv",
                    "-u", snmp_config["user"],
                    "-a", snmp_config["auth_type"],
                    "-A", "password"  # We use a placeholder for the actual run
                ])
            elif snmp_config["security_level"] == "auth_priv":
                cmd.extend([
                    "-l", "authPriv",
                    "-u", snmp_config["user"],
                    "-a", snmp_config["auth_type"],
                    "-A", "password",  # We use a placeholder for the actual run
                    "-x", snmp_config["privacy_type"],
                    "-X", "password"   # We use a placeholder for the actual run
                ])
    
    cmd.extend([f"{host}:{port}", "."])
    
    try:
        print(f"Executing: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=timeout)
        
        if process.returncode != 0:
            print(f"ERROR: snmpwalk failed: {stderr}")
            sys.exit(1)
        
        print(f"Collected {len(stdout.splitlines())} SNMP metrics")
        return stdout
    except subprocess.TimeoutExpired:
        print(f"ERROR: snmpwalk timed out after {timeout} seconds")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to run snmpwalk: {e}")
        sys.exit(1)

def parse_snmp_output(output):
    """Parse the snmpwalk output into a list of OIDs and values."""
    metrics = []
    
    for line in output.splitlines():
        # Match both iso. format and direct OID format
        iso_match = re.match(r'^iso\.([0-9\.]+) = (.+)$', line)
        oid_match = re.match(r'^([0-9\.]+) = (.+)$', line)
        
        if iso_match:
            oid = f"1.{iso_match.group(1)}"
            value = iso_match.group(2)
            metrics.append({"oid": oid, "value": value})
        elif oid_match:
            oid = oid_match.group(1)
            value = oid_match.group(2)
            metrics.append({"oid": oid, "value": value})
    
    return metrics

def identify_device_type(metrics):
    """Try to identify the device type from SNMP metrics."""
    system_desc = None
    
    # Look for system description
    for metric in metrics:
        if metric["oid"] == "1.3.6.1.2.1.1.1.0":
            system_desc = metric["value"]
            break
    
    if not system_desc:
        return "generic"
    
    # Extract from quotes if present
    if system_desc.startswith('STRING: '):
        system_desc = system_desc[8:].strip('"')
    
    if "OpenWrt" in system_desc:
        return "openwrt"
    elif "RouterOS" in system_desc:
        return "mikrotik"
    elif "Cisco IOS" in system_desc:
        return "cisco"
    elif "JUNOS" in system_desc:
        return "juniper"
    elif "Linux" in system_desc:
        return "linux"
    else:
        return "generic"

def get_interface_metrics(metrics):
    """Extract interface information from metrics."""
    interfaces = {}
    
    # Find interface names
    for metric in metrics:
        match = re.match(r'^1.3.6.1.2.1.2.2.1.2.(\d+)$', metric["oid"])
        if match:
            index = match.group(1)
            # Extract interface name from STRING: "name"
            name_match = re.match(r'STRING: "?([^"]+)"?', metric["value"])
            if name_match:
                name = name_match.group(1)
                # Clean the name (remove spaces, special chars)
                clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
                interfaces[index] = {"name": clean_name, "index": index}
    
    return interfaces

def generate_metrics_for_device(metrics, device_type, interfaces):
    """Generate appropriate metrics based on device type in the new OTel SNMP receiver format."""
    # This will hold our final OTel SNMP configuration
    config = {
        "resource_attributes": {},
        "attributes": {},
        "metrics": {}
    }
    
    # Define common attributes
    config["attributes"]["direction"] = {
        "enum": ["in", "out"]
    }
    
    config["attributes"]["interface"] = {
        "indexed_value_prefix": "interface"
    }
    
    config["attributes"]["protocol"] = {
        "enum": ["ip", "tcp", "udp", "icmp"]
    }
    
    # Add state attribute for CPU and memory metrics
    config["attributes"]["state"] = {
        "enum": ["user", "system", "idle", "used", "total", "cached"]
    }
    
    # Add period attribute for load average
    config["attributes"]["period"] = {
        "enum": ["1m", "5m", "15m"]
    }
    
    # Define resource attributes
    config["resource_attributes"]["device.id"] = {
        "oid": "1.3.6.1.2.1.1.5.0"  # System name
    }
    
    # The value key is not allowed in resource_attributes
    # Fix: use indexed_value_prefix or oid instead
    config["resource_attributes"]["device.type.name"] = {
        "indexed_value_prefix": device_type
    }
    
    # Add system uptime metric
    config["metrics"]["system.uptime"] = {
        "unit": "s",
        "gauge": {
            "value_type": "int"
        },
        "scalar_oids": [
            {
                "oid": "1.3.6.1.2.1.1.3.0"
            }
        ]
    }
    
    # Add interface metrics
    if interfaces:
        # Network interface throughput metrics
        config["metrics"]["network.io.packets"] = {
            "unit": "1",
            "sum": {
                "aggregation": "cumulative",
                "monotonic": True,
                "value_type": "int"
            },
            "column_oids": []
        }
        
        config["metrics"]["network.io.bytes"] = {
            "unit": "By",
            "sum": {
                "aggregation": "cumulative",
                "monotonic": True,
                "value_type": "int"
            },
            "column_oids": []
        }
        
        # Add interface in/out octets metrics
        for idx, interface in interfaces.items():
            # In octets
            config["metrics"]["network.io.bytes"]["column_oids"].append({
                "oid": f"1.3.6.1.2.1.2.2.1.10.{idx}",
                "attributes": [
                    {"name": "interface", "value": interface["name"]},
                    {"name": "direction", "value": "in"}
                ]
            })
            
            # Out octets
            config["metrics"]["network.io.bytes"]["column_oids"].append({
                "oid": f"1.3.6.1.2.1.2.2.1.16.{idx}",
                "attributes": [
                    {"name": "interface", "value": interface["name"]},
                    {"name": "direction", "value": "out"}
                ]
            })
            
            # In packets
            config["metrics"]["network.io.packets"]["column_oids"].append({
                "oid": f"1.3.6.1.2.1.2.2.1.11.{idx}",
                "attributes": [
                    {"name": "interface", "value": interface["name"]},
                    {"name": "direction", "value": "in"}
                ]
            })
            
            # Out packets
            config["metrics"]["network.io.packets"]["column_oids"].append({
                "oid": f"1.3.6.1.2.1.2.2.1.17.{idx}",
                "attributes": [
                    {"name": "interface", "value": interface["name"]},
                    {"name": "direction", "value": "out"}
                ]
            })
        
        # Add high capacity counters if available (for modern devices)
        hc_interfaces = [idx for idx, _ in interfaces.items() 
                         if any(m["oid"] == f"1.3.6.1.2.1.31.1.1.1.6.{idx}" for m in metrics)]
        
        if hc_interfaces:
            config["metrics"]["network.io.bytes.hc"] = {
                "unit": "By",
                "sum": {
                    "aggregation": "cumulative",
                    "monotonic": True,
                    "value_type": "int"
                },
                "column_oids": []
            }
            
            for idx in hc_interfaces:
                interface = interfaces[idx]
                # HC In octets
                config["metrics"]["network.io.bytes.hc"]["column_oids"].append({
                    "oid": f"1.3.6.1.2.1.31.1.1.1.6.{idx}",
                    "attributes": [
                        {"name": "interface", "value": interface["name"]},
                        {"name": "direction", "value": "in"}
                    ]
                })
                
                # HC Out octets
                config["metrics"]["network.io.bytes.hc"]["column_oids"].append({
                    "oid": f"1.3.6.1.2.1.31.1.1.1.10.{idx}",
                    "attributes": [
                        {"name": "interface", "value": interface["name"]},
                        {"name": "direction", "value": "out"}
                    ]
                })
    
    # Add CPU metrics
    if any(m["oid"] == "1.3.6.1.4.1.2021.11.50.0" for m in metrics):
        config["metrics"]["system.cpu"] = {
            "unit": "1",
            "gauge": {
                "value_type": "double"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.4.1.2021.11.50.0",
                    "attributes": [
                        {"name": "state", "value": "user"}
                    ]
                },
                {
                    "oid": "1.3.6.1.4.1.2021.11.52.0",
                    "attributes": [
                        {"name": "state", "value": "system"}
                    ]
                },
                {
                    "oid": "1.3.6.1.4.1.2021.11.53.0",
                    "attributes": [
                        {"name": "state", "value": "idle"}
                    ]
                }
            ]
        }
    
    # Add memory metrics
    if any(m["oid"] == "1.3.6.1.4.1.2021.4.5.0" for m in metrics):
        config["metrics"]["system.memory"] = {
            "unit": "By",
            "gauge": {
                "value_type": "int"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.4.1.2021.4.6.0",
                    "attributes": [
                        {"name": "state", "value": "used"}
                    ]
                },
                {
                    "oid": "1.3.6.1.4.1.2021.4.5.0",
                    "attributes": [
                        {"name": "state", "value": "total"}
                    ]
                }
            ]
        }
        
        # Add cached memory for Linux/OpenWrt
        if device_type in ["linux", "openwrt"] and any(m["oid"] == "1.3.6.1.4.1.2021.4.15.0" for m in metrics):
            config["metrics"]["system.memory"]["scalar_oids"].append({
                "oid": "1.3.6.1.4.1.2021.4.15.0",
                "attributes": [
                    {"name": "state", "value": "cached"}
                ]
            })
    
    # Add load average metrics
    if any(m["oid"] == "1.3.6.1.4.1.2021.10.1.3.1" for m in metrics):
        config["metrics"]["system.load"] = {
            "unit": "1",
            "gauge": {
                "value_type": "double"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.4.1.2021.10.1.3.1",
                    "attributes": [
                        {"name": "period", "value": "1m"}
                    ]
                },
                {
                    "oid": "1.3.6.1.4.1.2021.10.1.3.2",
                    "attributes": [
                        {"name": "period", "value": "5m"}
                    ]
                },
                {
                    "oid": "1.3.6.1.4.1.2021.10.1.3.3",
                    "attributes": [
                        {"name": "period", "value": "15m"}
                    ]
                }
            ]
        }
    
    # Add network protocol metrics - IP, TCP, UDP
    protocol_metrics = {}
    
    # IP metrics
    if any(m["oid"] == "1.3.6.1.2.1.4.3.0" for m in metrics):
        protocol_metrics["network.packets.ip"] = {
            "unit": "1",
            "sum": {
                "aggregation": "cumulative",
                "monotonic": True,
                "value_type": "int"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.2.1.4.3.0",  # IP packets received
                    "attributes": [
                        {"name": "direction", "value": "in"}
                    ]
                },
                {
                    "oid": "1.3.6.1.2.1.4.10.0",  # IP packets delivered
                    "attributes": [
                        {"name": "direction", "value": "out"}
                    ]
                }
            ]
        }
    
    # TCP metrics
    if any(m["oid"] == "1.3.6.1.2.1.6.10.0" for m in metrics):
        protocol_metrics["network.packets.tcp"] = {
            "unit": "1",
            "sum": {
                "aggregation": "cumulative",
                "monotonic": True,
                "value_type": "int"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.2.1.6.10.0",  # TCP segments received
                    "attributes": [
                        {"name": "direction", "value": "in"}
                    ]
                },
                {
                    "oid": "1.3.6.1.2.1.6.11.0",  # TCP segments sent
                    "attributes": [
                        {"name": "direction", "value": "out"}
                    ]
                }
            ]
        }
    
    # UDP metrics
    if any(m["oid"] == "1.3.6.1.2.1.7.1.0" for m in metrics):
        protocol_metrics["network.packets.udp"] = {
            "unit": "1",
            "sum": {
                "aggregation": "cumulative",
                "monotonic": True,
                "value_type": "int"
            },
            "scalar_oids": [
                {
                    "oid": "1.3.6.1.2.1.7.1.0",  # UDP datagrams received
                    "attributes": [
                        {"name": "direction", "value": "in"}
                    ]
                },
                {
                    "oid": "1.3.6.1.2.1.7.4.0",  # UDP datagrams sent
                    "attributes": [
                        {"name": "direction", "value": "out"}
                    ]
                }
            ]
        }
    
    config["metrics"].update(protocol_metrics)
    
    # Clean up empty sections
    if not config["resource_attributes"]:
        del config["resource_attributes"]
    if not config["attributes"]:
        del config["attributes"]
    if not config["metrics"]:
        # Fallback to basic metrics if none of the structured ones are available
        config["metrics"] = {
            "system.info": {
                "unit": "1",
                "gauge": {
                    "value_type": "int"
                },
                "scalar_oids": [
                    {"oid": "1.3.6.1.2.1.1.3.0"}  # System uptime
                ]
            }
        }
    
    return config

def generate_otel_config(host, port, snmp_config, metrics_config):
    """Generate the full OTel SNMP receiver configuration."""
    # Start with the SNMP connection config
    config = copy.deepcopy(snmp_config)
    
    # Add basic receiver settings
    config.update({
        "collection_interval": "60s",
        "endpoint": f"udp://{host}:{port}"
    })
    
    # Merge with the metrics configuration
    config.update(metrics_config)
    
    # Make sure version is correctly formatted with 'v' prefix
    if "version" in config and not config["version"].startswith("v"):
        config["version"] = f"v{config['version']}"
    
    return {"snmp": config}

def inject_into_otel_config(otel_config_path, snmp_config):
    """Inject SNMP receiver into existing OTel collector config."""
    try:
        with open(otel_config_path, 'r') as f:
            otel_config = yaml.safe_load(f)
            
            if otel_config is None:
                otel_config = {}
    except Exception as e:
        print(f"Warning: Could not read existing config at {otel_config_path}: {e}")
        print("Creating new configuration.")
        otel_config = {}
    
    # Ensure receivers section exists
    if 'receivers' not in otel_config:
        otel_config['receivers'] = {}
    
    # Add SNMP receiver
    otel_config['receivers'].update(snmp_config)
    
    # Ensure service section exists
    if 'service' not in otel_config:
        otel_config['service'] = {}
    
    # Ensure pipelines section exists
    if 'pipelines' not in otel_config['service']:
        otel_config['service']['pipelines'] = {}
    
    # Ensure metrics pipeline exists
    if 'metrics' not in otel_config['service']['pipelines']:
        otel_config['service']['pipelines']['metrics'] = {
            'receivers': [],
            'processors': [],
            'exporters': []
        }
    
    # Add SNMP receiver to metrics pipeline if not already there
    if 'snmp' not in otel_config['service']['pipelines']['metrics']['receivers']:
        otel_config['service']['pipelines']['metrics']['receivers'].append('snmp')
    
    # Return the updated config
    return otel_config

def main():
    parser = argparse.ArgumentParser(description="Generate OpenTelemetry SNMP receiver config from SNMP data")
    parser.add_argument("--host", required=True, help="Target host IP address")
    parser.add_argument("--port", type=int, default=161, help="SNMP port (default: 161)")
    parser.add_argument("--community", default="public", help="SNMP community string (default: public)")
    parser.add_argument("--version", choices=["auto", "1", "2c", "3"], default="auto", help="SNMP version (default: auto)")
    parser.add_argument("--user", default="otel", help="SNMPv3 username (default: otel)")
    parser.add_argument("--auth-type", choices=["MD5", "SHA"], default="MD5", help="SNMPv3 authentication type (default: MD5)")
    parser.add_argument("--privacy-type", choices=["DES", "AES"], default="DES", help="SNMPv3 privacy type (default: DES)")
    parser.add_argument("--security-level", choices=["no_auth_no_priv", "auth_no_priv", "auth_priv"], default="auth_priv", help="SNMPv3 security level (default: auth_priv)")
    parser.add_argument("--input", help="Input file with snmpwalk output (if not provided, snmpwalk will be executed)")
    parser.add_argument("--output", help="Output YAML file (default: otel_snmp_config.yaml)")
    parser.add_argument("--inject-into", help="Inject configuration into existing OTel collector config file")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Set up SNMP configuration based on version
    snmp_config = None
    if args.version == "auto":
        snmp_config = detect_snmp_version(args.host, args.port, args.community)
        if snmp_config is None:
            print("Could not auto-detect SNMP version. Please specify manually.")
            sys.exit(1)
    elif args.version == "1":
        snmp_config = {"version": "v1", "community": args.community}
    elif args.version == "2c":
        snmp_config = {"version": "v2c", "community": args.community}
    elif args.version == "3":
        snmp_config = {
            "version": "v3",
            "security_level": args.security_level,
            "user": args.user
        }
        
        if args.security_level in ["auth_no_priv", "auth_priv"]:
            snmp_config.update({
                "auth_type": args.auth_type,
                "auth_password": "${env:SNMP_AUTH_PASSWORD}"
            })
            
        if args.security_level == "auth_priv":
            snmp_config.update({
                "privacy_type": args.privacy_type,
                "privacy_password": "${env:SNMP_PRIVACY_PASSWORD}"
            })
    
    # Get SNMP data either from file or by running snmpwalk
    if args.input:
        try:
            with open(args.input, 'r') as f:
                snmp_output = f.read()
            print(f"Read {len(snmp_output.splitlines())} lines from {args.input}")
        except Exception as e:
            print(f"ERROR: Failed to read input file: {e}")
            sys.exit(1)
    else:
        snmp_output = run_snmpwalk(args.host, args.port, snmp_config)
    
    # Parse SNMP output
    metrics = parse_snmp_output(snmp_output)
    print(f"Parsed {len(metrics)} SNMP metrics")
    
    # Identify device type for specialized metrics
    device_type = identify_device_type(metrics)
    print(f"Detected device type: {device_type}")
    
    # Get interface information
    interfaces = get_interface_metrics(metrics)
    print(f"Found {len(interfaces)} interfaces:")
    for idx, interface in interfaces.items():
        print(f"  {idx}: {interface['name']}")
    
    # Generate appropriate metrics configuration
    metrics_config = generate_metrics_for_device(metrics, device_type, interfaces)
    print(f"Generated metrics configuration with {len(metrics_config.get('metrics', {}))} metrics")
    
    # Generate OTel receiver configuration
    otel_config = generate_otel_config(args.host, args.port, snmp_config, metrics_config)
    
    # If injection requested, update existing config
    if args.inject_into:
        full_config = inject_into_otel_config(args.inject_into, otel_config)
        output_file = args.inject_into
    else:
        full_config = {"receivers": otel_config}
        output_file = args.output or "otel_snmp_config.yaml"
    
    # Write configuration to file
    try:
        with open(output_file, 'w') as f:
            yaml.dump(full_config, f, default_flow_style=False, sort_keys=False)
        print(f"Configuration written to {output_file}")
    except Exception as e:
        print(f"ERROR: Failed to write configuration: {e}")
        sys.exit(1)
    
    print("\nOpenTelemetry SNMP Receiver configuration generated successfully!")
    if args.inject_into:
        print(f"Configuration injected into {args.inject_into}")
        print(f"Remember to set environment variables for SNMPv3 authentication if using v3:")
        print(f"  export SNMP_AUTH_PASSWORD=your_auth_password")
        print(f"  export SNMP_PRIVACY_PASSWORD=your_privacy_password")
    else:
        print(f"You can now use this configuration with the OpenTelemetry Collector.")

if __name__ == "__main__":
    main()
