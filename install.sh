#!/usr/bin/env bash
# Instala o Descompactador para o usuário atual (tudo em ~/.local; nada no sistema).
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/usr/bin/python3
BIN_DIR="$HOME/.local/bin"
SERVICEMENU_DIR="$HOME/.local/share/kio/servicemenus"
APPS_DIR="$HOME/.local/share/applications"
WRAPPER="$BIN_DIR/descompactador"

if ! "$PY" -c "import PySide6" 2>/dev/null; then
    echo "Erro: $PY não encontra o PySide6 (pacote python3-pyside6)." >&2
    exit 1
fi
command -v 7z >/dev/null || command -v 7zz >/dev/null || command -v 7za >/dev/null \
    || echo "Aviso: 7z não encontrado; zip/7z/iso dependerão do unar."
command -v unar >/dev/null || echo "Aviso: unar não encontrado; arquivos RAR não poderão ser extraídos."

mkdir -p "$BIN_DIR" "$SERVICEMENU_DIR" "$APPS_DIR"

# -P: não coloca a pasta atual no sys.path (o Dolphin abre o app dentro de pastas de downloads).
cat > "$WRAPPER" <<WRAP
#!/bin/sh
PYTHONPATH="$PROJ\${PYTHONPATH:+:\$PYTHONPATH}" exec $PY -P -m descompactador "\$@"
WRAP
chmod +x "$WRAPPER"

sed "s|@EXEC@|$WRAPPER|" "$PROJ/data/servicemenu.desktop" > "$SERVICEMENU_DIR/descompactador.desktop"
chmod +x "$SERVICEMENU_DIR/descompactador.desktop"   # o Plasma 6 exige service menus executáveis
sed "s|@EXEC@|$WRAPPER|" "$PROJ/data/app.desktop" > "$APPS_DIR/descompactador.desktop"

command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

echo "Instalado:"
echo "  $WRAPPER"
echo "  $SERVICEMENU_DIR/descompactador.desktop  (Dolphin: botão direito → Extrair todos juntos...)"
echo "  $APPS_DIR/descompactador.desktop  (menu de aplicativos)"
