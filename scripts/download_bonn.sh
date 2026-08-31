#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_DIR="$ROOT_DIR/datasets/bonn"
BASE_URL="https://www.ipb.uni-bonn.de/html/projects/rgbd_dynamic2019"
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

download_bonn_zip() {
    local name="$1"
    local target="$2"
    local archive="$DATASET_DIR/$name.zip"
    local url="$BASE_URL/$name.zip"

    if [ -e "$target" ]; then
        run rm -f "$archive" "$archive.aria2"
        echo "$name already exists at $target"
        return
    fi

    download_file "$url" "$archive"
    run unzip -n "$archive" -d "$DATASET_DIR"
    run rm -f "$archive" "$archive.aria2"
    echo "$name is ready at $target"
}

run mkdir -p "$DATASET_DIR"

download_bonn_zip rgbd_bonn_balloon "$DATASET_DIR/rgbd_bonn_balloon"
download_bonn_zip rgbd_bonn_balloon2 "$DATASET_DIR/rgbd_bonn_balloon2"
download_bonn_zip rgbd_bonn_balloon_tracking "$DATASET_DIR/rgbd_bonn_balloon_tracking"
download_bonn_zip rgbd_bonn_balloon_tracking2 "$DATASET_DIR/rgbd_bonn_balloon_tracking2"
download_bonn_zip rgbd_bonn_crowd "$DATASET_DIR/rgbd_bonn_crowd"
download_bonn_zip rgbd_bonn_crowd2 "$DATASET_DIR/rgbd_bonn_crowd2"
download_bonn_zip rgbd_bonn_crowd3 "$DATASET_DIR/rgbd_bonn_crowd3"
download_bonn_zip rgbd_bonn_kidnapping_box "$DATASET_DIR/rgbd_bonn_kidnapping_box"
download_bonn_zip rgbd_bonn_kidnapping_box2 "$DATASET_DIR/rgbd_bonn_kidnapping_box2"
download_bonn_zip rgbd_bonn_moving_nonobstructing_box "$DATASET_DIR/rgbd_bonn_moving_nonobstructing_box"
download_bonn_zip rgbd_bonn_moving_nonobstructing_box2 "$DATASET_DIR/rgbd_bonn_moving_nonobstructing_box2"
download_bonn_zip rgbd_bonn_moving_obstructing_box "$DATASET_DIR/rgbd_bonn_moving_obstructing_box"
download_bonn_zip rgbd_bonn_moving_obstructing_box2 "$DATASET_DIR/rgbd_bonn_moving_obstructing_box2"
download_bonn_zip rgbd_bonn_person_tracking "$DATASET_DIR/rgbd_bonn_person_tracking"
download_bonn_zip rgbd_bonn_person_tracking2 "$DATASET_DIR/rgbd_bonn_person_tracking2"
download_bonn_zip rgbd_bonn_placing_nonobstructing_box "$DATASET_DIR/rgbd_bonn_placing_nonobstructing_box"
download_bonn_zip rgbd_bonn_placing_nonobstructing_box2 "$DATASET_DIR/rgbd_bonn_placing_nonobstructing_box2"
download_bonn_zip rgbd_bonn_placing_nonobstructing_box3 "$DATASET_DIR/rgbd_bonn_placing_nonobstructing_box3"
download_bonn_zip rgbd_bonn_placing_obstructing_box "$DATASET_DIR/rgbd_bonn_placing_obstructing_box"
download_bonn_zip rgbd_bonn_removing_nonobstructing_box "$DATASET_DIR/rgbd_bonn_removing_nonobstructing_box"
download_bonn_zip rgbd_bonn_removing_nonobstructing_box2 "$DATASET_DIR/rgbd_bonn_removing_nonobstructing_box2"
download_bonn_zip rgbd_bonn_removing_obstructing_box "$DATASET_DIR/rgbd_bonn_removing_obstructing_box"
download_bonn_zip rgbd_bonn_static "$DATASET_DIR/rgbd_bonn_static"
download_bonn_zip rgbd_bonn_static_close_far "$DATASET_DIR/rgbd_bonn_static_close_far"
download_bonn_zip rgbd_bonn_synchronous "$DATASET_DIR/rgbd_bonn_synchronous"
download_bonn_zip rgbd_bonn_synchronous2 "$DATASET_DIR/rgbd_bonn_synchronous2"
download_bonn_zip rgbd_bonn_groundtruth_1mm_section "$DATASET_DIR/rgbd_bonn_groundtruth_1mm_section.ply"
