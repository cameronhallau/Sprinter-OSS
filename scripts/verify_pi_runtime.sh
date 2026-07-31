#!/bin/sh
set -eu

expected="0.83.0"
actual="$(pi --version | sed -nE 's/.*([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' | head -1)"
test "$actual" = "$expected"
test "$(node -p 'require("/opt/pi/node_modules/@earendil-works/pi-coding-agent/node_modules/brace-expansion/package.json").version')" = "5.0.9"
