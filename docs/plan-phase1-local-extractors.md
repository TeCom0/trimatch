# Phase 1, item 4: local extractors compared (plan)

Status: APPROVED 2026-11-19 (D1-D3), built and measured 2026-11-19/20.

## Why

- Real documents may never go to the Gemini free tier, because Google may use that data (decision 2026-11-12). A local extractor is the only way to run the Phase 1 real held-out set.
- The brief asks for 2–3 options compared on the same test set, with measured numbers.
- Scans get exact highlight boxes only with OCR word positions (box fix, 2026-11-17).

## This laptop (checked 2026-11-19)

| Part | |
|---|---|
| GPU | AMD Radeon RX 7600S, 8 GB (RDNA 3, gfx1102); no CUDA |
| CPU | Ryzen 7 7735HS, 8 cores / 16 threads |
| RAM | 15 GB |
| Installed | no Ollama, no Tesseract |

GPU support is unclear from public sources. Ollama's documentation is reported to list Windows ROCm support for the RX 7600 class (ROCm 7 driver), with Vulkan as the fallback. An older source says RDNA 3 on Windows is Vulkan-only. Nothing confirms the laptop part ([MindStudio](https://www.mindstudio.ai/blog/running-local-ai-amd-rocm-ollama-lm-studio), [runaihome](https://runaihome.com/blog/amd-rocm-local-ai-2026/), [vucense](https://vucense.com/dev-corner/ollama-on-windows-2026-install-guide/)). So **step 0 measures it before anything is built on it.**

## The options

| | How | Boxes | Why it's in |
|---|---|---|---|
| **A. OCR + local LLM** | OCR gives words with positions; a local text LLM (Qwen3, 4B or 8B, quantised) fills the same JSON schema as Gemini, from the OCR text laid out by lines | exact, from OCR words (the existing `snap.py`) | classic pipeline, cheap, works on CPU; OCR words are needed for scan boxes anyway |
| **B. Local vision LLM on the page** | Qwen2.5-VL 7B (quantised) reads the page image with the same prompt and schema as Gemini | snapped to PDF text or OCR words | closest local equivalent of what Gemini does today |
| **C. Gemini 3.5 Flash Lite** (baseline) | as today | snapped | the numbers to beat; already measured |

- **OCR engine for A and for scan boxes:** PaddleOCR models through RapidOCR (ONNX Runtime, CPU) against Tesseract 5 with French data. Both are Apache-2.0. Public comparisons disagree and none uses French invoices ([invoicedataextraction](https://invoicedataextraction.com/blog/python-ocr-library-comparison-invoices), [aekora](https://aekora.com/blog/best-local-ocr-document-models-2026)), so we measure on our dev documents. Measure: the share of ground-truth values found verbatim in the OCR output, per degradation. The better engine is kept.
- **Left out:** LayoutLMv3, because of its non-commercial licence and because it needs labelled fine-tuning. Surya, because of its licence questions and its weight on CPU. Either can be added later.

## Steps

0. **Hardware probe** (no project code): install Ollama, pull the smallest candidate, measure tokens/s on GPU (ROCm or Vulkan) and on CPU.
   - Gate: if a vision page takes over 3 minutes, option B runs on a smaller sample only, and the report says so.
1. **OCR adapter** (`extract/ocr.py`): words + boxes for PDFs (text layer) and images (OCR). Snapping uses it, so scans get exact boxes too.
2. **Extractors** `local-ocr-llm` and `local-vlm`. They use the same RDoc schema and parsing as Gemini, so validation and matching don't change, plus a disk cache like Gemini's. They run through Ollama's local HTTP API only, never a network service.
3. **Tuning on dev** (seed 1), 40 documents stratified by degradation, prompts only.
4. **One reported run per option on the held-out test split** (200 documents, overnight), plus e2e decisions. The report covers:
   - field, line and document accuracy per degradation
   - box placement
   - latency per page on this laptop
   - wrong drafts (must stay 0)
   - disk and RAM used
5. **Choose the default local extractor** from those numbers. It becomes the one allowed for real documents.

## Cost and downloads

All free, local and open-licensed (licences to be re-checked at install time):
- Ollama (MIT)
- Qwen3 and Qwen2.5-VL weights (Apache-2.0; about 3–6 GB each, quantised)
- RapidOCR and PP-OCR models (Apache-2.0)
- Tesseract 5 + French data (Apache-2.0)

Roughly 12–15 GB of downloads in total. No API cost.

## Decisions for Youness

- **D1. Candidates.** *Recommended:* A (OCR + Qwen3) and B (Qwen2.5-VL 7B) against the Gemini baseline, with the OCR engine picked by measurement.
- **D2. Installs and downloads** of the software and model weights above, about 12–15 GB. *Needs your explicit OK.*
- **D3. Long runs.** *Recommended:* run the test split overnight on the laptop, plugged in. If step 0 shows it would take more than 10 hours, report on a stratified 100-document subset of test instead, stated in the report.
