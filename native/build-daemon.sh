#!/bin/sh
set -eu
cd "$(dirname "$0")"
swiftc -O -o astra-daemon daemon.swift -framework AppKit -framework CoreGraphics -framework ScreenCaptureKit -framework ImageIO -framework UniformTypeIdentifiers
