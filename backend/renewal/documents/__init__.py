"""Mortgage statement and renewal-letter reading: text layer, OCR, bilingual fields.

Pipeline: acquire text per page (PDF text layer, else OCR) -> redact account
identifiers -> identify the lender -> extract fields with evidence -> run
cross-field consistency checks -> hand a review list to the user. Nothing here
feeds a calculation until the user has confirmed the fields.
"""
