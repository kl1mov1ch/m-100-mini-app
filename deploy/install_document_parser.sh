#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
environment="${DOCUMENT_DOCLING_ENV:-$PWD/.runtime/docling-venv}"
python3 -m venv "$environment"
"$environment/bin/pip" install --disable-pip-version-check --no-cache-dir -r backend/docling-requirements.txt
OMP_THREAD_LIMIT=1 OPENBLAS_NUM_THREADS=1 "$environment/bin/python" - <<'PY'
from docling.document_converter import DocumentConverter, NativePdfFormatOption
from docling.datamodel.pipeline_options import NativePdfPipelineOptions
from importlib.metadata import version
assert version('docling-slim') == '2.150.0'
print('Docling native PDF parser ready; OCR uses local Tesseract')
PY
