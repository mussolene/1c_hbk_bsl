# Data sources and 1C-related materials (`data/`)

## Purpose

Files under [`data/`](../data/) (including [`data/platform_api/`](../data/platform_api/)) support completions, hovers, and metadata indexing. They must come from **sources you have the right to publish**.

## Documented lineage (repository)

The [README](../README.md) states that global platform API data is aligned with **[vsc-language-1c-bsl](https://github.com/1c-syntax/vsc-language-1c-bsl)** (MIT), which is a common community source for 1C platform API listings.

## Maintainer checklist (NDA / confidentiality)

Legal review cannot be automated. Before adding or updating data from internal or partner sources, confirm:

1. **Right to distribute** — the material is public, licensed, or you have permission to redistribute it in an open repository.
2. **No customer data** — no production infobases, dumps, or client-specific identifiers.
3. **Trademarks** — use of “1C”, “1С:Предприятие”, etc. follows applicable trademark/naming policies for **descriptive** compatibility statements (as in README), not implied endorsement.

If any past commit accidentally contained confidential material, follow the incident response steps in [SECURITY_AUDIT.md](SECURITY_AUDIT.md) (rotation + optional history rewrite).

## bsl-language-server (LGPL)

The project may reference **diagnostic codes** (e.g. BSLLS-style identifiers) for parity documentation. **bsl-language-server** is LGPL-3.0; this repository does **not** ship or link its Java implementation as a dependency of the Python analyzer. Using rule **names/codes** for documentation is a separate question from combining code; if your policy requires stricter separation, keep references in docs only and avoid copying substantial excerpts from LGPL-covered source files.
