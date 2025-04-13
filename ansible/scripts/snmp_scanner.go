package main

import (
	"fmt"
	"net"
	"os"
	"strings"
	"time"

	"github.com/gosnmp/gosnmp"
	"gopkg.in/yaml.v3"
)

// SNMPConfig holds the discovered SNMP configuration for an endpoint.
type SNMPConfig struct {
	Endpoint  string `yaml:"endpoint"`
	Version   string `yaml:"version"`
	Community string `yaml:"community,omitempty"`
	User      string `yaml:"user,omitempty"`
}

// OTelSNMPReceiverConfig represents the structure for the OpenTelemetry SNMP receiver configuration.
type OTelSNMPReceiverConfig struct {
	Receivers map[string]map[string][]SNMPConfig `yaml:"receivers"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: go run snmp_scanner.go <ip_range> [community] [user] [auth_password] [priv_password]")
		fmt.Println("Example: go run snmp_scanner.go 192.168.1.0/24 public")
		fmt.Println("Example with SNMPv3: go run snmp_scanner.go 192.168.1.1/32 privateuser authSHA1 authpassword privAES128 privpassword")
		return
	}

	ipRange := os.Args[1]
	var community string
	var user, authPassword, privPassword string

	if len(os.Args) > 2 {
		community = os.Args[2]
	}
	if len(os.Args) > 3 {
		user = os.Args[3]
	}
	if len(os.Args) > 4 {
		authPassword = os.Args[4]
	}
	if len(os.Args) > 5 {
		privPassword = os.Args[5]
	}

	ips, err := expandIPRange(ipRange)
	if err != nil {
		fmt.Println("Error expanding IP range:", err)
		return
	}

	discoveredConfigs := []SNMPConfig{}

	for _, ip := range ips {
		fmt.Printf("Scanning %s...\n", ip)
		config := probeSNMP(ip, community, user, authPassword, privPassword)
		if config != nil {
			discoveredConfigs = append(discoveredConfigs, *config)
		}
	}

	if len(discoveredConfigs) > 0 {
		fmt.Println("\n--- Discovered SNMP Endpoints ---")
		for _, config := range discoveredConfigs {
			fmt.Printf("Endpoint: %s, Version: %s", config.Endpoint, config.Version)
			if config.Community != "" {
				fmt.Printf(", Community: %s", config.Community)
			}
			if config.User != "" {
				fmt.Printf(", User: %s", config.User)
			}
			fmt.Println()
		}

		otelConfig := OTelSNMPReceiverConfig{
			Receivers: map[string]map[string][]SNMPConfig{
				"snmp": {
					"scans": discoveredConfigs,
				},
			},
		}

		yamlData, err := yaml.Marshal(&otelConfig)
		if err != nil {
			fmt.Println("Error marshaling YAML:", err)
			return
		}

		fmt.Println("\n--- OpenTelemetry SNMP Receiver Configuration ---")
		fmt.Println("# Paste this under the 'receivers' section in your OTel Collector configuration")
		fmt.Println(string(yamlData))
	} else {
		fmt.Println("\nNo SNMP endpoints discovered in the specified range.")
	}
}

func expandIPRange(ipRange string) ([]string, error) {
	var ips []string
	if strings.Contains(ipRange, "/") {
		ip, ipnet, err := net.ParseCIDR(ipRange)
		if err != nil {
			return nil, err
		}
		for ip := ip.Mask(ipnet.Mask); ipnet.Contains(ip); inc(ip) {
			ips = append(ips, ip.String())
		}
		// Remove the network address
		if len(ips) > 0 {
			ips = ips[1:]
		}
		// Remove the broadcast address (if applicable)
		if len(ips) > 0 {
			lastIP := net.ParseIP(ips[len(ips)-1])
			broadcast := net.IP(make([]byte, len(lastIP)))
			copy(broadcast, lastIP)
			for i := len(broadcast) - 1; i >= 0; i-- {
				broadcast[i]++
				if broadcast[i] > 0 {
					break
				}
			}
			if ipnet.Contains(broadcast) && ips[len(ips)-1] == broadcast.String() {
				ips = ips[:len(ips)-1]
			}
		}
	} else {
		ips = append(ips, ipRange)
	}
	return ips, nil
}

func inc(ip net.IP) {
	for j := len(ip) - 1; j >= 0; j-- {
		ip[j]++
		if ip[j] > 255 {
			ip[j] = 0
		} else {
			break
		}
	}
}

func probeSNMP(ip, community, user, authPassword, privPassword string) *SNMPConfig {
	versions := []gosnmp.SnmpVersion{gosnmp.Version1, gosnmp.Version2c, gosnmp.Version3}
	communities := []string{"public"}
	if community != "" {
		communities = append([]string{community}, communities...)
	}

	for _, version := range versions {
		addr := net.JoinHostPort(ip, "161")
		params := &gosnmp.GoSNMP{
			Target:    addr,
			Version:   version,
			Timeout:   2 * time.Second,
			Community: "",
		}

		if version == gosnmp.Version3 {
			params.Community = ""
			if user != "" {
				params.SecurityParameters = &gosnmp.UsmSecurityParameters{
					UserName:                 user,
					AuthenticationProtocol:   gosnmp.SHA,
					AuthenticationPassphrase: authPassword,
					PrivacyProtocol:          gosnmp.AES,
					PrivacyPassphrase:        privPassword,
				}

			} else {
				params.SecurityParameters = &gosnmp.UsmSecurityParameters{
					UserName:               "public",
					AuthenticationProtocol: gosnmp.NoAuth,
					PrivacyProtocol:        gosnmp.NoPriv,
				}
			}
		} else {
			for _, comm := range communities {
				params.Community = comm
				err := params.Connect()
				if err == nil {
					_, err2 := params.Get([]string{"1.3.6.1.2.1.1.1.0"}) // SysDescr
					if params.Conn != nil {
						params.Conn.Close()
					}
					if err2 == nil {
						snmpVersion := "v1"
						if version == gosnmp.Version2c {
							snmpVersion = "v2c"
						}
						return &SNMPConfig{
							Endpoint:  fmt.Sprintf("udp://%s:161", ip),
							Version:   snmpVersion,
							Community: comm,
						}
					}
				}
			}
			continue // Move to the next SNMP version if v1/v2c failed with all communities
		}

	}
	return nil
}
