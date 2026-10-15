# Installed OCR And RBC Demonstration

## Bundled Engine

The official Tesseract GitHub release was checked before installation. The latest
release was 5.5.3, with the Windows x64 installer 5.5.3.20260724. The downloaded
installer matched GitHub's published SHA-256:

    bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4

It was installed into runtime/ocr. The engine actually executed and reported
Tesseract v5.5.3.20260724 with Leptonica 1.87.0. Official tessdata_best English
and French models are bundled from commit:

    e12c65a915945e4c28e237a9b52bc4a8f39a0cec

The runtime retains upstream documentation and Apache licenses. Runtime binary,
library, model and vendor-documentation lines are excluded from source-code
growth measurements. The ZIP includes the Windows runtime so this user does not
have to reinstall OCR on this computer. Other operating systems need their own
Tesseract binary. The standard Python application requirements still apply.

Primary sources:

- https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3
- https://tesseract-ocr.github.io/tessdoc/ReleaseNotes
- https://github.com/tesseract-ocr/tessdata_best/tree/e12c65a915945e4c28e237a9b52bc4a8f39a0cec

## Document Workflow

The document screen now accepts PDF, PNG, JPEG, WebP and TIFF within an 8 MB
limit. Searchable PDF pages are read directly. Scanned PDF pages are rendered
within explicit dimension limits and read through local Tesseract. PDFs remain
limited to 16 pages, with bounded text and a per-document OCR time budget.

English, French and combined OCR are selectable. French text recognition is
available, but the existing semantic field-label parser primarily handles English
contract labels. French-only fields may need manual entry; recognition is not a
claim of complete bilingual legal interpretation.

The reader uses the existing evidence auditor. It keeps original/renewal scopes
separate, does not promote conflicting facts, links candidates to source passages
and requires manual field verification. OCR word confidence is a model score,
not the percentage probability that a contract field is correct. In the real
RBC-labelled scan check, mean word confidence was approximately 96% and all
seven expected English fields were recovered.

Uploads are not permanently saved. OCR uses temporary normalized local page
images, which are removed after the engine finishes. No uploaded document is
sent to a third-party OCR service. Native PDF extraction, OCR and loan calculations
still require the running local server; only the cached browser helper works
after that server stops.

## RBC Sample

RBC Royal Bank is now the default demonstration lender in the online and offline
workspaces. The generated PDF and scan explicitly say they are hypothetical,
not issued or endorsed by RBC and not rate quotes. No RBC logo, authentication,
account connection or personalized rate has been added. Real user-entered lender
names remain editable and are not forcibly renamed to RBC.

## Verification

The previously skipped camera OCR tests now execute. Real tests cover the RBC
raster scan, image-only PDF, bilingual model setting, field values, source evidence,
engine failure, malformed inputs, dimension limits and API uploads. The browser
also loaded the sample scan and showed seven fields with page excerpts and the
actual engine version. The release sidecar records complete source and extracted
archive suite results, checksums and the OCR-enabled local deployment.
