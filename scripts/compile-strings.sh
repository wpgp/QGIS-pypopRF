#!/bin/bash
set -euo pipefail
if (( $# < 2 )); then
    printf 'Usage: %s /path/to/lrelease locale [locale ...]\n' "$0" >&2
    exit 1
fi
translation_compiler=$1
shift
for locale in "$@"; do
    if [[ ! "$locale" =~ ^[A-Za-z0-9_@-]+$ ]]; then
        printf 'Invalid locale: %s\n' "$locale" >&2
        exit 1
    fi
    "$translation_compiler" "i18n/$locale.ts"
done
