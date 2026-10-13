#!/bin/bash

# Source this helper only when testing the native QGIS adapter on Linux.
# The numerical engine has its own environment and must not inherit these paths.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    printf 'Source this script: source scripts/run-env-linux.sh [/usr or custom prefix]\n' >&2
    exit 1
fi

export QGIS_PREFIX_PATH="${1:-/usr}"
export PYTHONPATH="$QGIS_PREFIX_PATH/share/qgis/python:$QGIS_PREFIX_PATH/share/qgis/python/plugins${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$QGIS_PREFIX_PATH/bin:$PATH"
if [[ "$QGIS_PREFIX_PATH" != /usr ]]; then
    export LD_LIBRARY_PATH="$QGIS_PREFIX_PATH/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
printf 'Native QGIS prefix: %s\n' "$QGIS_PREFIX_PATH"
