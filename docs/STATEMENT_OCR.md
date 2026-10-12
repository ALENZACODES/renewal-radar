# Statement and renewal-letter reading

`backend/renewal/documents/` reads a mortgage statement or renewal letter (PDF
or photo) and returns proposed fields for the user to confirm.
`POST /api/v5/documents/statement` exposes it. File bytes are read in memory and
dropped after the request.

## Pipeline

1. **Text** (`text.py`). Each PDF page uses its text layer when it has at least
   40 characters. Otherwise the page is rendered at 300 dpi and sent to the OCR
   engine. Photos (PNG, JPEG, TIFF) always go to OCR. Limits: 12 MB, 20 pages, no
   password-protected files. OCR is pluggable (`OcrEngine`); `TesseractEngine`
   uses English and French. Without an OCR engine, image uploads return a clear
   422 asking for a text PDF or manual entry.
2. **Redaction** (`redact.py`). Account, loan, transit and card numbers and SINs
   are masked to their last four characters before anything is stored, logged
   or returned. Amounts, rates, dates and short references stay readable.
3. **Lender** (`lenders.py`). Names and aliases for 16 Canadian lenders, English
   and French. Letterhead (first eight lines) counts three times as much as the
   body, so "compare with TD" in a Scotiabank letter still reads as Scotiabank.
4. **Fields** (`labels.py`, `values.py`, `fields.py`). English and French labels
   for balance, current and renewal rate, maturity, payment, term, amortization,
   frequency, rate type and lump-sum privilege. Values are read from the rest of
   the label's line, or the next line for two-row tables. Parsers handle
   `$412,345.67`, `450 000,00 $`, `5,49 %`, `1er mars 2027`, `03/15/2027`,
   `19 years 6 months` and `5-year`.
5. **Checks** (`checks.py`). Maturity in the past or more than ten years out;
   identical current and renewal rate; term longer than amortization; and the
   payment recomputed from balance, rate and amortization with the
   Canadian semi-annual compounding engine (3% tolerance).

## Confidence and review

| Where the value was found | Confidence |
|---|---|
| Same line as the label, text layer | 0.90 |
| Next line, text layer | 0.75 |
| Any OCR page | minus 0.10 |
| Rate type inferred from a "5-year fixed" phrase | 0.70 |

Fields under 0.85, and every field touched by a failed or warning check, are
listed in `review`. Required fields that weren't found are in `missing`. The UI
must not feed any value into a calculation until the user has confirmed it.

## Privacy

- On-device OCR is the default for the mobile apps; the server path exists for
  web uploads.
- Account identifiers are masked before preview text leaves the server.
- No file bytes or raw page images are stored.
- Any cloud vision fallback needs explicit per-scan consent and a zero-retention
  provider. It is not part of this module.
