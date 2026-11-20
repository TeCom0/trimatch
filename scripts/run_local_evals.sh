#!/usr/bin/env bash
# Overnight held-out runs of the local extractors (docs/plan-phase1-local-extractors.md).
# Needs Ollama on 127.0.0.1:11434 and Odoo (for the e2e decisions). Logs to data/eval_local.log.
cd "$(dirname "$0")/.." || exit 1
log=data/eval_local.log
for split in test e2e; do
  for ex in local-vlm local-ocr-llm; do
    echo "=== $(date -Is) $split $ex" >> "$log"
    extra=""; [ "$split" = e2e ] && extra="--reset-bills"
    PYTHONIOENCODING=utf-8 uv run --project backend python -m eval.run --split "$split" --extractor "$ex" $extra >> "$log" 2>&1
    echo "=== $(date -Is) done $split $ex exit $?" >> "$log"
  done
done
