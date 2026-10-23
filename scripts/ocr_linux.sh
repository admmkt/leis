#!/bin/sh
# Substituto Linux de scripts/bin/ocr (Vision do macOS): pdftoppm + Tesseract, páginas separadas por \f.
# O workflow copia este arquivo para scripts/bin/ocr; comum.ocr_pdf chama "ocr arquivo.pdf".
set -e
d=$(mktemp -d)
trap 'rm -rf "$d"' EXIT
pdftoppm -r 300 -gray -png "$1" "$d/p"
for p in "$d"/p-*.png; do
  OMP_THREAD_LIMIT=1 tesseract "$p" stdout --tessdata-dir "$(dirname "$0")/tessdata" -l por --oem 1 --psm 3 2>/dev/null
  printf '\f'
done
