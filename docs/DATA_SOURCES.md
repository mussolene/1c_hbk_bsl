# Data sources and 1C-related materials (`src/onec_hbk_bsl/data/`)

## Purpose

Files under
[`src/onec_hbk_bsl/data/`](https://github.com/mussolene/1c_hbk_bsl/tree/main/src/onec_hbk_bsl/data/)
(including
[`src/onec_hbk_bsl/data/platform_api/`](https://github.com/mussolene/1c_hbk_bsl/tree/main/src/onec_hbk_bsl/data/platform_api/))
support completions, hovers, and metadata indexing. They must come from
**sources you have the right to publish**.

## Documented lineage

Global platform API data is aligned with **[vsc-language-1c-bsl](https://github.com/1c-syntax/vsc-language-1c-bsl)** (MIT), which is a common community source for 1C platform API listings. Keep this file and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) as the public provenance trail; the README should stay focused on product usage.

## Maintainer checklist (NDA / confidentiality)

Legal review cannot be automated. Before adding or updating data from internal or partner sources, confirm:

1. **Right to distribute** — the material is public, licensed, or you have permission to redistribute it in an open repository.
2. **No customer data** — no production infobases, dumps, or client-specific identifiers.
3. **Trademarks** — use of “1C”, “1С:Предприятие”, etc. follows applicable trademark/naming policies for **descriptive** compatibility statements (as in README), not implied endorsement.

If any past commit accidentally contained confidential material, follow the incident response steps in [SECURITY_AUDIT.md](SECURITY_AUDIT.md) (rotation + optional history rewrite).

## Diagnostic Alias Provenance

The project accepts compatibility aliases for diagnostic selection and suppression comments.
The aliases are local runtime metadata; no adjacent analyzer is launched, linked, or required.
Adapted diagnostic prose is vendored in this repository and covered by the provenance
record in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
