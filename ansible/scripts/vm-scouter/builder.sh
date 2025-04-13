#!/bin/bash
# build.sh
PLATFORMS=("linux/amd64" "linux/arm64" "darwin/amd64" "windows/amd64")

for platform in "${PLATFORMS[@]}"; do
    IFS="/" read -r -a parts <<< "$platform"
    OS="${parts[0]}"
    ARCH="${parts[1]}"
    
    echo "Building for $OS/$ARCH..."
    
    # Set environment variables for cross-compilation
    GOOS="$OS" GOARCH="$ARCH" go build -o "scouter-$OS-$ARCH$([ "$OS" == "windows" ] && echo ".exe")" main.go
done