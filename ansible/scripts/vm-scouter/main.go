package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// DiscoveredService represents a service detected on the system
type DiscoveredService struct {
	Name       string   `json:"name"`
	Port       int      `json:"port"`
	ProcessID  string   `json:"process_id,omitempty"`
	Executable string   `json:"executable,omitempty"`
	Type       string   `json:"type"`
	Protocol   string   `json:"protocol"`
	Version    string   `json:"version,omitempty"`
	Metadata   []string `json:"metadata,omitempty"`
}

// DiscoveryResult contains all discovery information
type DiscoveryResult struct {
	Hostname      string                       `json:"hostname"`
	DiscoveryTime string                       `json:"discovery_time"`
	Services      []DiscoveredService          `json:"services"`
	Applications  map[string]ApplicationDetail `json:"applications"`
}

// ApplicationDetail contains details about discovered applications
type ApplicationDetail struct {
	Name     string            `json:"name"`
	Version  string            `json:"version"`
	Type     string            `json:"type"`
	Path     string            `json:"path,omitempty"`
	Metadata map[string]string `json:"metadata,omitempty"`
}

func main() {
	// Create discovery result
	result := DiscoveryResult{
		DiscoveryTime: time.Now().Format(time.RFC3339),
		Applications:  make(map[string]ApplicationDetail),
	}

	// Get hostname
	hostname, err := os.Hostname()
	if err == nil {
		result.Hostname = hostname
	} else {
		result.Hostname = "unknown"
	}

	// Discover open ports and services
	result.Services = discoverServices()

	// Detect common applications
	detectApplications(&result)

	// Output results in format suitable for Ansible facts
	writeAnsibleFact(result)
}

func discoverServices() []DiscoveredService {
	services := []DiscoveredService{}

	// Common ports to check
	commonPorts := []int{22, 80, 443, 3306, 5432, 6379, 8080, 8443, 27017}

	for _, port := range commonPorts {
		address := fmt.Sprintf("127.0.0.1:%d", port)
		conn, err := net.DialTimeout("tcp", address, 1*time.Second)
		if err == nil {
			conn.Close()

			// Try to identify what's running on this port
			service := identifyService(port)
			services = append(services, service)
		}
	}

	// Also use netstat/ss to find listening ports we might have missed
	if isCommandAvailable("netstat") {
		cmd := exec.Command("netstat", "-tulpn")
		output, err := cmd.Output()
		if err == nil {
			lines := strings.Split(string(output), "\n")
			for _, line := range lines {
				if strings.Contains(line, "LISTEN") {
					parseNetstatLine(line, &services)
				}
			}
		}
	} else if isCommandAvailable("ss") {
		cmd := exec.Command("ss", "-tulpn")
		output, err := cmd.Output()
		if err == nil {
			lines := strings.Split(string(output), "\n")
			for _, line := range lines {
				if strings.Contains(line, "LISTEN") {
					parseSsLine(line, &services)
				}
			}
		}
	}

	return services
}

func identifyService(port int) DiscoveredService {
	service := DiscoveredService{
		Port:     port,
		Protocol: "tcp",
		Type:     "unknown",
	}

	// Basic service identification by port
	switch port {
	case 22:
		service.Name = "ssh"
		service.Type = "remote_access"
	case 80:
		service.Name = "http"
		service.Type = "web_server"
	case 443:
		service.Name = "https"
		service.Type = "web_server"
	case 3306:
		service.Name = "mysql"
		service.Type = "database"
	case 5432:
		service.Name = "postgresql"
		service.Type = "database"
	case 6379:
		service.Name = "redis"
		service.Type = "cache"
	case 8080:
		service.Name = "http_alt"
		service.Type = "web_server"
	case 27017:
		service.Name = "mongodb"
		service.Type = "database"
	default:
		service.Name = fmt.Sprintf("unknown_port_%d", port)
	}

	return service
}

func parseNetstatLine(line string, services *[]DiscoveredService) {
	// Sample line: "tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      1234/nginx"
	parts := strings.Fields(line)
	if len(parts) < 7 {
		return
	}

	addrParts := strings.Split(parts[3], ":")
	if len(addrParts) < 2 {
		return
	}

	port, err := strconv.Atoi(addrParts[len(addrParts)-1])
	if err != nil {
		return
	}

	service := DiscoveredService{
		Port:     port,
		Protocol: "tcp",
		Type:     "unknown",
	}

	// Check if process info is available
	if len(parts) >= 7 && strings.Contains(parts[6], "/") {
		processParts := strings.Split(parts[6], "/")
		service.ProcessID = processParts[0]
		service.Executable = processParts[1]
		service.Name = processParts[1]

		// Try to determine service type
		if strings.Contains(service.Executable, "nginx") || strings.Contains(service.Executable, "apache") {
			service.Type = "web_server"
		} else if strings.Contains(service.Executable, "mysql") || strings.Contains(service.Executable, "postgres") {
			service.Type = "database"
		} else if strings.Contains(service.Executable, "ssh") {
			service.Type = "remote_access"
		}
	}

	// Add to services list if not already present
	for _, s := range *services {
		if s.Port == service.Port {
			return
		}
	}
	*services = append(*services, service)
}

func parseSsLine(line string, services *[]DiscoveredService) {
	// Sample line: "tcp   LISTEN 0      128    *:80                   *:*                  users:(("nginx",pid=1234,fd=6))"
	parts := strings.Fields(line)
	if len(parts) < 5 {
		return
	}

	// Find the part that contains the port
	var addrPart string
	for _, part := range parts {
		if strings.Contains(part, ":") {
			addrPart = part
			break
		}
	}

	addrParts := strings.Split(addrPart, ":")
	if len(addrParts) < 2 {
		return
	}

	port, err := strconv.Atoi(addrParts[len(addrParts)-1])
	if err != nil {
		return
	}

	service := DiscoveredService{
		Port:     port,
		Protocol: "tcp",
		Type:     "unknown",
	}

	// Try to extract process info
	pidRegex := regexp.MustCompile(`pid=(\d+)`)
	execRegex := regexp.MustCompile(`\("([^"]+)"`)

	pidMatch := pidRegex.FindStringSubmatch(line)
	if len(pidMatch) > 1 {
		service.ProcessID = pidMatch[1]
	}

	execMatch := execRegex.FindStringSubmatch(line)
	if len(execMatch) > 1 {
		service.Executable = execMatch[1]
		service.Name = execMatch[1]

		// Try to determine service type
		if strings.Contains(service.Executable, "nginx") || strings.Contains(service.Executable, "apache") {
			service.Type = "web_server"
		} else if strings.Contains(service.Executable, "mysql") || strings.Contains(service.Executable, "postgres") {
			service.Type = "database"
		} else if strings.Contains(service.Executable, "ssh") {
			service.Type = "remote_access"
		}
	}

	// Add to services list if not already present
	for _, s := range *services {
		if s.Port == service.Port {
			return
		}
	}
	*services = append(*services, service)
}

func detectApplications(result *DiscoveryResult) {
	// Try to detect common applications based on standard paths or commands
	detectWebServers(result)
	detectDatabases(result)
	detectLanguageRuntimes(result)
}

func detectWebServers(result *DiscoveryResult) {
	// Check for NGINX
	if isCommandAvailable("nginx") {
		cmd := exec.Command("nginx", "-v")
		output, err := cmd.CombinedOutput()
		version := "unknown"
		if err == nil {
			versionRegex := regexp.MustCompile(`nginx/(\d+\.\d+\.\d+)`)
			matches := versionRegex.FindStringSubmatch(string(output))
			if len(matches) > 1 {
				version = matches[1]
			}
		}

		result.Applications["nginx"] = ApplicationDetail{
			Name:    "NGINX",
			Version: version,
			Type:    "web_server",
		}
	}

	// Check for Apache
	if isCommandAvailable("apache2") || isCommandAvailable("httpd") {
		cmd := exec.Command("apache2", "-v")
		if !isCommandAvailable("apache2") {
			cmd = exec.Command("httpd", "-v")
		}

		output, err := cmd.CombinedOutput()
		version := "unknown"
		if err == nil {
			versionRegex := regexp.MustCompile(`Apache/(\d+\.\d+\.\d+)`)
			matches := versionRegex.FindStringSubmatch(string(output))
			if len(matches) > 1 {
				version = matches[1]
			}
		}

		result.Applications["apache"] = ApplicationDetail{
			Name:    "Apache HTTP Server",
			Version: version,
			Type:    "web_server",
		}
	}
}

func detectDatabases(result *DiscoveryResult) {
	// Check for MySQL/MariaDB
	if isCommandAvailable("mysql") {
		cmd := exec.Command("mysql", "--version")
		output, err := cmd.CombinedOutput()
		version := "unknown"
		dbType := "MySQL"

		if err == nil {
			if strings.Contains(string(output), "MariaDB") {
				dbType = "MariaDB"
				versionRegex := regexp.MustCompile(`MariaDB\s+(\d+\.\d+\.\d+)`)
				matches := versionRegex.FindStringSubmatch(string(output))
				if len(matches) > 1 {
					version = matches[1]
				}
			} else {
				versionRegex := regexp.MustCompile(`Distrib\s+(\d+\.\d+\.\d+)`)
				matches := versionRegex.FindStringSubmatch(string(output))
				if len(matches) > 1 {
					version = matches[1]
				}
			}
		}

		result.Applications["mysql"] = ApplicationDetail{
			Name:    dbType,
			Version: version,
			Type:    "database",
		}
	}

	// Check for PostgreSQL
	if isCommandAvailable("psql") {
		cmd := exec.Command("psql", "--version")
		output, err := cmd.CombinedOutput()
		version := "unknown"

		if err == nil {
			versionRegex := regexp.MustCompile(`(\d+\.\d+)`)
			matches := versionRegex.FindStringSubmatch(string(output))
			if len(matches) > 1 {
				version = matches[1]
			}
		}

		result.Applications["postgresql"] = ApplicationDetail{
			Name:    "PostgreSQL",
			Version: version,
			Type:    "database",
		}
	}
}

func detectLanguageRuntimes(result *DiscoveryResult) {
	// Check for Python
	if isCommandAvailable("python") || isCommandAvailable("python3") {
		cmd := exec.Command("python", "--version")
		if !isCommandAvailable("python") {
			cmd = exec.Command("python3", "--version")
		}

		output, err := cmd.CombinedOutput()
		version := "unknown"
		if err == nil {
			versionRegex := regexp.MustCompile(`Python\s+(\d+\.\d+\.\d+)`)
			matches := versionRegex.FindStringSubmatch(string(output))
			if len(matches) > 1 {
				version = matches[1]
			}
		}

		result.Applications["python"] = ApplicationDetail{
			Name:    "Python",
			Version: version,
			Type:    "language_runtime",
		}
	}

	// Check for Node.js
	if isCommandAvailable("node") {
		cmd := exec.Command("node", "--version")
		output, err := cmd.CombinedOutput()
		version := "unknown"
		if err == nil {
			version = strings.TrimSpace(string(output))
			// Remove v prefix if present
			version = strings.TrimPrefix(version, "v")
		}

		result.Applications["nodejs"] = ApplicationDetail{
			Name:    "Node.js",
			Version: version,
			Type:    "language_runtime",
		}
	}

	// Check for Java
	if isCommandAvailable("java") {
		cmd := exec.Command("java", "-version")
		output, err := cmd.CombinedOutput()
		version := "unknown"
		if err == nil {
			versionRegex := regexp.MustCompile(`version\s+"([^"]+)"`)
			matches := versionRegex.FindStringSubmatch(string(output))
			if len(matches) > 1 {
				version = matches[1]
			}
		}

		result.Applications["java"] = ApplicationDetail{
			Name:    "Java",
			Version: version,
			Type:    "language_runtime",
		}
	}
}

func isCommandAvailable(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

func writeAnsibleFact(result DiscoveryResult) {
	// Ensure the facts.d directory exists
	factsDir := "/etc/ansible/facts.d"
	if _, err := os.Stat(factsDir); os.IsNotExist(err) {
		os.MkdirAll(factsDir, 0755)
	}

	// Create the facts file
	factFile := fmt.Sprintf("%s/discovery.fact", factsDir)
	file, err := os.Create(factFile)
	if err != nil {
		fmt.Printf("Error creating fact file: %v\n", err)
		return
	}
	defer file.Close()

	// Format the data as a JSON object with a top-level "discovery" key
	factData := map[string]DiscoveryResult{
		"discovery": result,
	}

	// Write JSON to the facts file
	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(factData); err != nil {
		fmt.Printf("Error writing fact file: %v\n", err)
		return
	}

	// Ensure the fact file is readable
	os.Chmod(factFile, 0644)
}
