"""Consent-based homeowner-to-broker lead handoff.

A lead exists only when a homeowner explicitly asks to be contacted by a named
brokerage after seeing the required disclosures. Contact details are encrypted
at rest, duplicates are folded together, scoring is a published formula, and
delivery to the broker's CRM uses signed webhooks with retries.
"""
