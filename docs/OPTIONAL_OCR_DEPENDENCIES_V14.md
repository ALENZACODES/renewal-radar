# V14 Optional OCR Dependencies and GitHub Adapter Inputs

V14 adds the dependency-aware adapter layer.

The goal is to use the best ideas from current OCR/document-intelligence
projects without making the default app heavy or fragile. Renewal Radar now has
a built-in registry for optional adapters and a stable input contract for each
one.

## Included As Optional Profiles

- Docling: structured document conversion, tables, formulas, layout and reading
  order.
- Unstructured: document partitioning, elements, chunks, lists and tables.
- PaddleOCR: OCR pipelines, PP-OCRv6 direction, PP-Structure-style parsing and
  future browser/edge ideas.
- Surya: line detection, layout blocks and image-heavy OCR pages.
- Marker: Markdown, JSON, chunks and force-OCR conversion shape.
- olmOCR: PDF linearization, benchmark mindset and OCR quality checks.

These are recorded in code and in `requirements-ocr-optional.txt`, but they are
not in the default `requirements.txt`.

## Why Optional Instead Of Required?

Some of these packages require large model downloads, GPU/CPU planning, license
review, or document-specific installation extras. Making them mandatory would
make the app harder to run and test.

V14 instead does this:

- detect whether an optional package is installed
- rank the best adapter profile for the document
- return the exact inputs that adapter would need
- return validation checks for money, rates, dates, tables and evidence
- keep local deterministic review as the fallback

## Built-In Input Contracts

Every adapter profile describes:

- accepted input types
- required inputs
- default options
- expected outputs
- validation checks
- privacy controls
- output mapping into Renewal Radar evidence nodes

This means a future adapter can be connected without changing the mortgage
reasoning layer. The external parser reads; Renewal Radar still understands,
checks, asks and explains.

## Default Runtime Policy

The default app remains runnable with the base dependencies only. Optional OCR
packages are installed deliberately, not silently. The app does not copy GitHub
source code and does not import optional engines unless they are present.
