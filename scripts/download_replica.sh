#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_DIR="$ROOT_DIR/datasets"
ZIP_PATH="$DATASET_DIR/Replica.zip"
URL="https://cvg-data.inf.ethz.ch/nice-slam/data/Replica.zip"
DRY_RUN=0

if [ -z "${DOWNLOAD_TOOL:-}" ]; then
    if command -v aria2c >/dev/null 2>&1; then
        DOWNLOAD_TOOL=aria2c
    else
        DOWNLOAD_TOOL=wget
    fi
fi

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
elif [ "${1:-}" != "" ]; then
    echo "Usage: $0 [--dry-run]" >&2
    exit 2
fi

read -r -a EXTRA_WGET_ARGS <<< "${WGET_ARGS:-}"
read -r -a EXTRA_ARIA2_ARGS <<< "${ARIA2_ARGS:-}"

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
        return
    fi
    "$@"
}

download_file() {
    local url="$1"
    local output="$2"
    local output_dir
    local output_name
    local connections

    case "$DOWNLOAD_TOOL" in
        aria2c | aria2)
            if ! command -v aria2c >/dev/null 2>&1; then
                echo "aria2c is not installed; set DOWNLOAD_TOOL=wget to use wget" >&2
                exit 1
            fi
            output_dir="$(dirname "$output")"
            output_name="$(basename "$output")"
            connections="${ARIA2_CONNECTIONS:-16}"
            run aria2c \
                --continue=true \
                --max-connection-per-server="$connections" \
                --split="$connections" \
                --min-split-size=1M \
                --allow-overwrite=true \
                --auto-file-renaming=false \
                --dir "$output_dir" \
                --out "$output_name" \
                --no-conf=true \
                "${EXTRA_ARIA2_ARGS[@]}" \
                "$url"
            ;;
        wget)
            run wget -c "${EXTRA_WGET_ARGS[@]}" -O "$output" "$url"
            ;;
        *)
            echo "Unsupported DOWNLOAD_TOOL=$DOWNLOAD_TOOL; use aria2c or wget" >&2
            exit 2
            ;;
    esac
}

run mkdir -p "$DATASET_DIR"

if [ ! -d "$DATASET_DIR/replica" ]; then
    download_file "$URL" "$ZIP_PATH"
    run unzip -n "$ZIP_PATH" -d "$DATASET_DIR"

    if [ -d "$DATASET_DIR/Replica" ]; then
        run mv "$DATASET_DIR/Replica" "$DATASET_DIR/replica"
    fi
fi

run rm -f "$ZIP_PATH" "$ZIP_PATH.aria2"
echo "Replica dataset is ready at $DATASET_DIR/replica"
