#!/bin/sh
# Compila el ayudante WireGuard (poorsdrvpn) para Linux x86-64/ARM64 y Windows.
# Necesita Go (p. ej. GOROOT en ~/.cache/go-toolchain/go). Sin CGO: binarios
# estáticos que se empaquetan en src/poorsdr/_vendor/bin.
set -e
GO=${GO:-$HOME/.cache/go-toolchain/go/bin/go}
cd "$(dirname "$0")/poorsdrvpn"
OUT=../../../src/poorsdr/_vendor/bin
mkdir -p "$OUT"
GOOS=linux   GOARCH=amd64 CGO_ENABLED=0 "$GO" build -trimpath -ldflags "-s -w" -o "$OUT/poorsdrvpn-linux-amd64" .
GOOS=linux   GOARCH=arm64 CGO_ENABLED=0 "$GO" build -trimpath -ldflags "-s -w" -o "$OUT/poorsdrvpn-linux-arm64" .
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 "$GO" build -trimpath -ldflags "-s -w" -o "$OUT/poorsdrvpn-windows-amd64.exe" .
ls -la "$OUT"
