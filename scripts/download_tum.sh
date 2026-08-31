#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_DIR="$ROOT_DIR/datasets/tum"
BASE_URL="https://vision.in.tum.de/rgbd/dataset"
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

download_tum_sequence() {
    local group="$1"
    local name="$2"
    local archive="$DATASET_DIR/$name.tgz"
    local target="$DATASET_DIR/$name"
    local url="$BASE_URL/$group/$name.tgz"

    if [ -d "$target" ]; then
        run rm -f "$archive" "$archive.aria2"
        echo "$name already exists at $target"
        return
    fi

    download_file "$url" "$archive"
    run tar -xzf "$archive" -C "$DATASET_DIR"
    run rm -f "$archive" "$archive.aria2"
    echo "$name is ready at $target"
}

run mkdir -p "$DATASET_DIR"

download_tum_sequence freiburg1 rgbd_dataset_freiburg1_desk
download_tum_sequence freiburg1 rgbd_dataset_freiburg1_desk2
download_tum_sequence freiburg1 rgbd_dataset_freiburg1_room
download_tum_sequence freiburg2 rgbd_dataset_freiburg2_desk_with_person
download_tum_sequence freiburg2 rgbd_dataset_freiburg2_xyz
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_long_office_household
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_sitting_halfsphere
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_sitting_rpy
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_sitting_static
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_sitting_xyz
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_walking_halfsphere
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_walking_rpy
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_walking_static
download_tum_sequence freiburg3 rgbd_dataset_freiburg3_walking_xyz
