# V13 Contract Research Radar Concept

V13 keeps the public GitHub ecosystem useful without making Renewal Radar depend
on it at runtime.

The idea is simple:

1. Research what strong document intelligence systems are doing.
2. Record the useful ideas: layout awareness, table preservation, line
   detection, OCR quality checks, JSON/Markdown document conversion and
   evidence-first outputs.
3. Keep the actual app runnable without downloading those projects, models or
   new Python packages.
4. Implement the mortgage-specific reasoning in local Renewal Radar code.

## Why not import everything?

Projects such as Docling, Unstructured, PaddleOCR, olmOCR, Marker and Surya are
valuable, but they are not small switches. Some need model downloads, some have
large runtime stacks, some target general document conversion instead of
Canadian mortgage renewal review, and none of them can certify lender payout
amounts.

For this app, the safer foundation is a local deterministic layer:

- Extract fields from OCR text.
- Explain every value with evidence IDs.
- Flag missing or conflicting contract details.
- Estimate visible math only when the needed fields are present.
- Ask the lender for certified payout and penalty details.
- Keep raw OCR text out of public outputs.

## What V13 adds

`backend/renewal/ocr/contract_math_v13.py` adds Canadian mortgage math and
disclosure auditing. It explains formulas for:

- contract discount
- three-month interest
- posted-rate-minus-discount IRD scenario
- term timeline from mortgage date to maturity
- remaining months to maturity
- renewal timing and disclosure prompts

`backend/renewal/ocr/research_radar_v13.py` adds the research radar. It maps
public web/GitHub sources to local adapter tasks. For example:

- Docling and Unstructured influence structured evidence and element handling.
- PaddleOCR and Surya influence future OCR adapter slots.
- olmOCR influences testable quality gates.
- Marker influences stable JSON/Markdown conversion targets.
- FCAC guidance influences Canadian mortgage disclosure prompts.

The key policy is:

- no external project imports
- no model downloads
- no copied GitHub source code
- no new package dependency required to run V13

## Mortgage-specific reasoning

Generic OCR can read text, but it does not automatically understand that:

- posted rate, contract rate and renewal offered rate can mean different things
- a contract discount may affect IRD calculations
- three-month interest and IRD are often compared, but lender formulas differ
- mortgage date, term and maturity must be checked together
- payment amount may include taxes or insurance
- a written payout statement controls penalty and discharge values

V13 turns those ideas into local code and tests. The output is not legal advice
or lender certification; it is a structured review aid that tells the reviewer
what was found, what is missing and what to ask next.
