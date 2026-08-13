#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    config_dir="${YTSAGE_CONFIG_DIR:-/config}"
    download_dir="${YTSAGE_DOWNLOAD_DIR:-/downloads}"

    mkdir -p "$config_dir" "$download_dir"
    chown -R ytsage:ytsage "$config_dir"
    chown ytsage:ytsage "$download_dir"

    exec gosu ytsage "$@"
fi

exec "$@"
