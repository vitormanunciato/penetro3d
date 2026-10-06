#!/usr/bin/env bash
# Monta o instalador do Penetro3D para Windows — a partir do Linux.
#
# Não precisa de Windows nem de Wine: o Python oficial para Windows vem dos MSIs do
# python.org (extraídos com msiextract), as bibliotecas vêm como wheels win_amd64 do
# PyPI e o instalador é compilado com o NSIS. É o mesmo script que o GitHub Actions
# roda a cada versão publicada.
#
#   Ubuntu/Debian:  sudo apt install msitools nsis unzip curl python3.13
#   uso:            instalador/construir_windows.sh
#   resultado:      dist/Penetro3D-Setup.exe e dist/Penetro3D-Setup.exe.sha256
#
# Variáveis opcionais: PY_VER (versão do Python embutido), PY_HOST (python 3.13 do
# Linux usado para pré-compilar os .pyc), CACHE (pasta de downloads reaproveitados).
set -euo pipefail

PY_VER="${PY_VER:-3.13.16}"
PLOTLY_VER="2.35.2"
PLOTLY_SHA256="6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603"

# SHA-256 dos MSIs oficiais do Python 3.13.16 (python.org). Tudo o que entra no
# instalador é conferido: um arquivo corrompido ou trocado no caminho para o build.
declare -A MSI_SHA256=(
  [core]=507599467fafc5e8783961bd76db6e5a206d58bc968f06728c8a3865fc7337af
  [exe]=fa39afc12c0778464273167046d7755c93902ecbc2293682724fdb7023f07cca
  [lib]=ee15c9b1cd71465a60f7a37cf0528e0446398ff94020c0075514c43ab0655d3f
  [tcltk]=968fc0acb37c42439ae4cf96181ee2e8148a89a22707414d980f7a2a84c2e67b
)

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
OBRA="$RAIZ/build"
CACHE="${CACHE:-$OBRA/cache}"
PALCO="$OBRA/palco"                     # o que vai para dentro do instalador
DIST="$RAIZ/dist"
PY_HOST="${PY_HOST:-$(command -v python3.13 || command -v python3)}"

for cmd in msiextract makensis unzip curl "$PY_HOST"; do
  command -v "$cmd" >/dev/null || { echo "falta o programa: $cmd" >&2; exit 1; }
done
"$PY_HOST" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version' || {
  echo "PY_HOST precisa ser Python 3.13 (os .pyc precisam casar com o Python embutido)" >&2
  exit 1; }

VERSAO="$("$PY_HOST" -c "import sys; sys.path.insert(0, '$RAIZ/app'); import penetro3d_versao as v; print(v.VERSAO)")"
echo "== Penetro3D $VERSAO · Python $PY_VER (Windows x64)"

mkdir -p "$CACHE/msi" "$CACHE/wheels" "$DIST"
rm -rf "$PALCO"
mkdir -p "$PALCO/python" "$PALCO/app"

# ── 1. Python oficial para Windows ─────────────────────────────────────────────
# core = interpretador e DLLs; exe = python.exe/pythonw.exe; lib = biblioteca padrão;
# tcltk = tkinter, que é a janela do programa.
for parte in core exe lib tcltk; do
  msi="$CACHE/msi/$PY_VER-$parte.msi"
  [ -s "$msi" ] || curl -fsSL -o "$msi" "https://www.python.org/ftp/python/$PY_VER/amd64/$parte.msi"
  if [ "$PY_VER" = "3.13.16" ]; then
    echo "${MSI_SHA256[$parte]}  $msi" | sha256sum -c --quiet - || {
      echo "SHA-256 do $parte.msi não confere — apague $msi e rode de novo" >&2; exit 1; }
  else
    echo "aviso: PY_VER=$PY_VER sem SHA-256 fixado no script; $parte.msi não conferido" >&2
  fi
  msiextract -C "$PALCO/python" "$msi" >/dev/null
done
test -f "$PALCO/python/pythonw.exe" && test -f "$PALCO/python/DLLs/_tkinter.pyd"

# ── 2. Bibliotecas (wheels para Windows, versões exatas) ───────────────────────
# --require-hashes: cada wheel precisa bater com o SHA-256 escrito no requirements
"$PY_HOST" -m pip download -q -r "$RAIZ/requirements-win.txt" --no-deps --require-hashes \
  --only-binary=:all: --platform win_amd64 --python-version 3.13 \
  --implementation cp --abi cp313 --abi abi3 --abi none -d "$CACHE/wheels"

SP="$PALCO/python/Lib/site-packages"
mkdir -p "$SP"
"$PY_HOST" - "$RAIZ/requirements-win.txt" "$CACHE/wheels" "$SP" "$PALCO/python" <<'PY'
"""Instala cada wheel listado no requirements: descompacta em site-packages e
espalha as pastas .data como o pip faria (data/ vai para a raiz do Python)."""
import glob, os, re, shutil, sys, zipfile
req, pasta, sp, raiz = sys.argv[1:]
pinos = [l.split()[0].split('==') for l in open(req, encoding='utf-8')
         if l.strip() and not l.startswith('#')]
norm = lambda s: re.sub(r'[-_.]+', '_', s).lower()
for nome, versao in pinos:
    # nome E versão: o cache pode guardar o wheel da versão anterior de um pacote
    achados = [w for w in glob.glob(os.path.join(pasta, '*.whl'))
               if norm(os.path.basename(w).split('-')[0]) == norm(nome)
               and os.path.basename(w).split('-')[1] == versao]
    if len(achados) != 1:
        sys.exit(f'wheel de {nome}=={versao}: esperava 1, achei {len(achados)}')
    with zipfile.ZipFile(achados[0]) as z:
        z.extractall(sp)
    for data in glob.glob(os.path.join(sp, '*.data')):
        for sub in os.listdir(data):
            origem = os.path.join(data, sub)
            if sub in ('purelib', 'platlib'):
                destino = sp
            elif sub == 'data':
                destino = raiz
            else:                         # scripts/headers: não servem num app fechado
                continue
            for item in os.listdir(origem):
                if sub == 'data' and item == 'Scripts':
                    continue
                alvo = os.path.join(destino, item)
                if os.path.isdir(os.path.join(origem, item)):
                    shutil.copytree(os.path.join(origem, item), alvo, dirs_exist_ok=True)
                else:
                    shutil.copy2(os.path.join(origem, item), alvo)
        shutil.rmtree(data)
    print(f'  + {os.path.basename(achados[0])}')
PY
test -f "$PALCO/python/msvcp140.dll"

# ── 3. Programa, plotly.js e exemplos ──────────────────────────────────────────
# só os arquivos versionados no git: nada de rascunho local entra no instalador
if git -C "$RAIZ" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$RAIZ" ls-files -z app | tar -C "$RAIZ" --null -T - -cf - | tar -C "$PALCO" -xf -
else
  cp -r "$RAIZ/app/." "$PALCO/app/"
fi
mkdir -p "$PALCO/app/vendor"
js="$CACHE/plotly-$PLOTLY_VER.min.js"
[ -s "$js" ] || curl -fsSL -o "$js" "https://cdn.plot.ly/plotly-$PLOTLY_VER.min.js"
echo "$PLOTLY_SHA256  $js" | sha256sum -c --quiet -
cp "$js" "$PALCO/app/vendor/plotly.min.js"
mkdir -p "$PALCO/exemplos"
cp "$RAIZ/exemplos/"*.kml "$RAIZ/exemplos/"*.xlsx "$PALCO/exemplos/"
cp "$RAIZ/LEIA-ME.txt" "$PALCO/" 2>/dev/null || true

# ── 4. Enxugar ─────────────────────────────────────────────────────────────────
# Nada disso é usado pelo programa; tirar encurta o download e a instalação.
P="$PALCO/python"
rm -rf "$P/Lib/test" "$P/Lib/idlelib" "$P/Lib/turtledemo" "$P/Lib/ensurepip" \
       "$P/Lib/lib2to3" "$P/Lib/tkinter/test" "$P/Lib/venv" "$P/libs" "$P/include" \
       "$P/Doc" "$P/Tools" "$P/NEWS.txt" "$P/tcl/tk8.6/demos" "$P/tcl/tix"* \
       "$P/DLLs/"_test*.pyd "$P/DLLs/"_ctypes_test.pyd "$P/DLLs/"xxlimited*.pyd
find "$PALCO" -name '__pycache__' -type d -prune -exec rm -rf {} +
# (só pastas "tests"/"test"; "testing" fica — numpy.testing e pandas.testing são
# importados por dentro das próprias bibliotecas)
find "$SP" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
rm -rf "$SP/matplotlib/mpl-data/sample_data" "$SP/pandas/tests"
find "$SP" \( -name '*.pyi' -o -name '*.pxd' -o -name '*.pyx' -o -name '*.c' \
     -o -name '*.h' -o -name '*.lib' \) -delete
test -f "$SP/numpy/testing/__init__.py"

# ── 5. Pré-compilar (.pyc) ─────────────────────────────────────────────────────
# Sem isso a primeira abertura do programa demora bem mais. unchecked-hash: o .pyc
# vale enquanto o instalador não trocar o arquivo — e quem troca é sempre ele.
"$PY_HOST" -m compileall -q -j 0 --invalidation-mode unchecked-hash \
  -s "$PALCO" -p "" "$PALCO/python/Lib" "$PALCO/app"

# ── 6. Instalador ──────────────────────────────────────────────────────────────
TAM_KB=$(du -sk "$PALCO" | cut -f1)
makensis -V2 -INPUTCHARSET UTF8 \
  -DVERSAO="$VERSAO" -DPALCO="$PALCO" -DTAMANHO_KB="$TAM_KB" \
  -DSAIDA="$DIST/Penetro3D-Setup.exe" -DICONE="$RAIZ/app/icone.ico" \
  "$RAIZ/instalador/penetro3d.nsi"

# o programa instalado confere este hash antes de rodar uma atualização
(cd "$DIST" && sha256sum Penetro3D-Setup.exe > Penetro3D-Setup.exe.sha256)
ls -la "$DIST/Penetro3D-Setup.exe" "$DIST/Penetro3D-Setup.exe.sha256"
echo "== pronto: dist/Penetro3D-Setup.exe ($((TAM_KB / 1024)) MB instalado)"
