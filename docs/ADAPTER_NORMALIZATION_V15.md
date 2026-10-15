# V15 Adapter Output Normalization

V15 adds the layer that lets Renewal Radar accept outputs shaped like current
OCR/document projects without importing those projects directly.

Supported shapes:

- Docling-style structured pages, text spans and tables
- Unstructured-style elements and chunks
- PaddleOCR-style OCR line boxes, scores and table blocks
- Surya-style text lines, layout blocks and page tables
- Marker-style Markdown, chunks, blocks and JSON-like tables
- olmOCR-style linearized text and quality flags

The normalizer converts those inputs into:

- redacted text spans
- page-level OCR text
- normalized tables
- quality signals
- validation issues

Then the quality harness runs that normalized result through the existing
contract-intelligence stack:

- V12 evidence graph
- V13 mortgage math audit
- V13 lender packet
- V14 dependency plan

This keeps the external engines as optional readers while Renewal Radar remains
the local mortgage-understanding layer.

## Reconciliation

The workbench can compare multiple adapter candidates for the same mortgage
document. V15 now adds a reconciliation pass on top of that comparison. It
re-runs the selected and non-selected candidates through the deterministic
contract extractor, gathers field votes and chooses a review value for:

- balance
- contract rate
- posted rate
- contract discount
- offered rate
- term months
- amortization months
- mortgage start date
- maturity date
- payment amount
- payment frequency

Each field is labelled as `consensus`, `conflict`, `single_source` or
`missing`. The output still tells the reviewer to verify against the source
document. Reconciliation is not proof that an adapter read the page correctly;
it is a structured way to find where adapters agree or disagree.

## Benchmark suite

The benchmark suite creates synthetic adapter-shaped payloads for Marker,
PaddleOCR, Docling, Unstructured, Surya and olmOCR. It includes:

- complete renewal text
- OCR spelling noise such as `intrest` and `differental`
- thin rate-only excerpts
- low-confidence line OCR
- table-heavy structured output
- two-adapter consensus and conflict cases

These cases run through the same normalizer, quality harness and reconciliation
code as real adapter output. This gives the project a repeatable guardrail when
adapter contracts change: a new reader can be added by mapping its output into
spans, tables and page text, then checking that the benchmark cases still behave
as expected.

## Current adapter references

The V15 adapter shapes are based on public project interfaces and release notes
available during the October 2026 build:

- PaddleOCR / PP-OCRv6 and PaddleOCR-VL 1.6 for modern OCR and document parsing
- Docling for structured document conversion and pluggable OCR engines
- Surya for OCR, layout and line detection style outputs
- Marker for PDF-to-Markdown and chunk/block output patterns
- Unstructured for element-style document partitioning
- olmOCR for linearized PDF/document text

No source code from those repositories is copied into Renewal Radar. The code in
this repository is the adapter contract, normalization, scoring, reconciliation
and benchmark layer that lets those tools be used later without making them
mandatory base dependencies.
