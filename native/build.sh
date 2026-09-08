#!/bin/sh
set -eu
cd "$(dirname "$0")"
swiftc -O -o astra-bridge main.swift -framework AppKit -framework CoreGraphics -framework ScreenCaptureKit -framework ImageIO -framework UniformTypeIdentifiers
