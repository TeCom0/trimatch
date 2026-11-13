# Decisions

Format: date · decision · why · alternatives rejected. Newest first.

## 2026-11-12 (Phase 0 interview)
- **Name: trimatch.** Repo `TeCom0/trimatch`, folder `C:\dev\trimatch`. Says "three-way match" in English; renaming later is cheap.
- **Repo public from day one.** Visible history for recruiters; safety comes from gitignored `data/`, denied `.env`, synthetic data only.
- **No deadline, strict done-list.** Quality over speed; scope guard enforced by SPEC section 9.
- **ERP: Odoo 20 Community, self-hosted Docker, pinned dated tag; fallback 19.0.** Free (LGPL). Latest stable at decision time.
- **ERP API: JSON-2 only** (`/json/2/<model>/<method>`, bot user + API key). XML-RPC/JSON-RPC deprecated since 19 (removal date: docs say 20, third-party blogs say 22 for self-hosted; irrelevant since we don't use them).
- **Fake company: Casablanca hotel-restaurant group** with produce / beverages / cleaning suppliers. Different units and (expected) VAT treatments, realistic short deliveries. Rejected: building-materials distributor (uniform VAT, fewer interesting cases).
- **Slice extractor: Gemini Flash vision, free tier, synthetic docs only.** Fastest path end-to-end at zero cost; free-tier data may be used by Google, so real docs never go there. Local OCR + LLM (Ollama/Vulkan; RX 7600S not on official ROCm lists) comes in Phase 1 and is the only path allowed for real docs. Rejected for slice: local-first (driver risk before anything works).
- **No FastAPI or UI in the slice.** Package + CLI; API arrives with the review screen in Phase 1.
- **Short delivery and price change pulled into the slice** (brief had them in Phase 1). Without a mismatch the three-way match can't fail, so the demo proves nothing. Duplicate invoice stays in Phase 1.
- **VAT rates in config, not code.** Item-level rates unverified (secondary sources conflict, tax.gov.ma not machine-readable); must be checked against CGI 2026 by hand.

## 2026-11-13
- **VAT verified against CGI 2026** (docs/research/vat-cgi-2026.md): only 20%, 10% and exempt in 2026. Odoo 20's `l10n_ma` 7%/14% taxes are obsolete and not used.
- **Supplier 1 swapped from fresh fruit/veg to meat, fish and dairy.** The CGI exempts meat, fish and milk explicitly (art. 91-I-A), but has no exemption for fresh fruit/veg sold by a wholesaler, so their treatment is unclear. Result: every rate in the demo cites an article, and the three invoices cover exempt-only, 10%+20%, and exempt+20%.
- **Schema adds `tp_number`, `payment_terms`, `exemption_ref`** to cover art. 145-III mentions.
- **Seed runs inside the container via `odoo shell`, not over the API** (step 1 plan approved). The seed creates the bot's API key so it can't authenticate with it; the ORM gives idempotency and receipt validation. The pipeline still uses JSON-2 only.
- **PostgreSQL 16** (Odoo 20 `MIN_PG_VERSION = 16`, read from source).
