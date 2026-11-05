#!/usr/bin/env bash
# Remove o que o install.sh criou.
set -euo pipefail

rm -f "$HOME/.local/bin/descompactador" \
      "$HOME/.local/share/kio/servicemenus/descompactador.desktop" \
      "$HOME/.local/share/applications/descompactador.desktop"
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
echo "Descompactador removido."
