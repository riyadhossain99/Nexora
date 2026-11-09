#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/start.sh" "$@"
