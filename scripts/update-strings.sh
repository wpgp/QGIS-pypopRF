#!/bin/bash
# Supply the Qt-appropriate pylupdate executable explicitly (Qt 5 or Qt 6).
set -euo pipefail
if (( $# < 2 )); then
    printf 'Usage: %s /path/to/pylupdate locale [locale ...]\n' "$0" >&2
    exit 1
fi
translation_updater=$1
shift
plugin_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$plugin_root"
sources=(qgis_pypoprf.py gui/forms/main_dialog.ui)
while IFS= read -r -d '' source; do
    sources+=("$source")
done < <(find gui controllers services -type f -name '*.py' -print0)
mkdir -p i18n
for locale in "$@"; do
    if [[ ! "$locale" =~ ^[A-Za-z0-9_@-]+$ ]]; then
        printf 'Invalid locale: %s\n' "$locale" >&2
        exit 1
    fi
    "$translation_updater" "${sources[@]}" -ts "i18n/$locale.ts"
done
