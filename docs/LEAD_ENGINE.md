# Lead engine

`backend/renewal/leads/` hands a homeowner to a named brokerage only when the
homeowner asks for it. The plan's rule: never share a renewal letter or
personal details with a broker or lender without explicit, informed consent.

## Consent (`consent.py`)

- Wording is versioned. The form shows `GET /api/v5/leads/consent-text` and
  sends back the version and SHA-256 digest of exactly what was shown.
- `agreed` must be literally `true` (no pre-ticked boxes). Consent older than an
  hour, from the future, or for an out-of-date version is rejected.
- The homeowner picks contact methods (email, phone) and the brokerage is named.
  The wording covers what is shared, the fact that brokers may be paid by
  lenders and must disclose it (FSRA), and how to withdraw.
- The full consent record is stored with the lead.

## Identity and privacy (`identity.py`)

- Emails are normalised (case, Gmail dots and `+tags`) and phones go to E.164.
- Duplicate detection uses keyed HMAC-SHA256 hashes per brokerage
  (`RR_LEAD_DEDUPE_SECRET`), so the hash table can't be reversed or matched
  across brokerages. A repeat within 90 days increments `submissions` on the
  existing lead instead of creating another.
- Contact details are encrypted at rest with Fernet (`RR_LEAD_KEY`). Brokers
  see a masked first name, email and phone, and a balance band, not the exact
  balance. `POST .../leads/{id}/reveal` unmasks one lead and writes
  `lead_contact_revealed` to the workspace audit trail.
- Withdrawal (`DELETE /api/v5/leads/{id}` with the one-time withdraw token)
  erases the contact, drops the duplicate keys, keeps a tombstone and notifies
  the broker's CRM.

## Score (`scoring.py`)

| Part | Points |
|---|---|
| Timing | 40 if renewal is 0 to 120 days out, 30 if overdue, 25 for 120 to 240, 10 later, 5 with no date |
| Savings | (current rate - BoC posted 5-year) x balance per year, 1 point per $150, max 30 |
| Readiness | 15 for an uploaded statement, 15 for a completed analysis |

Bands: hot (70 or more), warm (40 to 69), nurture. No personal attributes
(age, postal code, income) are used.

## CRM webhooks (`webhooks.py`)

- `Renewal-Radar-Signature: t=<unix>,v1=<hmac-sha256 of "t.body">` and an
  `Idempotency-Key` header. Receivers call `verify()`, which rejects
  signatures more than five minutes old.
- HTTPS only. Retries on network errors, 408, 429 and 5xx after 30 s, 2 min,
  10 min, 1 h and 6 h, then dead-letter. Other 4xx responses go straight to
  dead-letter.
- Payloads never include contact details: the broker pulls them through the
  audited reveal endpoint.

## Configuration

| Variable | Purpose |
|---|---|
| `RR_LEAD_KEY` | Fernet key for contact encryption (`Vault.new_key()`) |
| `RR_LEAD_DEDUPE_SECRET` | 32+ character secret for duplicate hashes |

Without both, the lead endpoints return 503.
