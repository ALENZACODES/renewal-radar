# V17 On-Device Mortgage Helper

## Concept

The free helper is a local intent classifier followed by bounded, evidence-linked
answer functions. It is intentionally not presented as a downloaded LLM or an
unrestricted chat model. A 144-example corpus covers 18 mortgage topics. The
classifier is trained in the browser; all inference and answer assembly stay on
the device. There is no remote inference call, token fee, model download or API key.

`helper-model.js` defines the intent training examples. `helper-classifier.js`
normalizes spelling variants and uses IDF-weighted multinomial Naive Bayes.
For an intent c and word features x, scores combine the log prior of c and
weighted log likelihoods of the observed words. Smoothing avoids zero probabilities.
Confidence and ambiguity thresholds route unsupported questions to an explicit
fallback. These scores are classification signals, not probabilities that a
document is correct or that a mortgage will be approved.

`helper-context.js` whitelists relevant structured evidence and workspace inputs.
It excludes uploaded bytes, whole OCR text, session access tokens and arbitrary
object properties. Original, renewal and payout facts remain separate. Date/rate
bounds, conflicting evidence and unknown fields are preserved.

`helper-answers.js` supplies responses for contract rates, discounts, IRD, term,
amortization, renewal dates, maturity, payments, comparisons, switch conditions,
prepayments and public rates. Evidence references retain page/line excerpts.
An absence of an IRD clause never means the penalty is zero. Original discount
equals original posted rate minus original contract rate only when those facts
belong to the same scope. This is percentage-point arithmetic, not a percentage
change in price. Existing backend calculations remain the authority for loan math.

## Review And Privacy

`helper-review.js` records reviewed, needs-followup and unreviewed decisions with
bounded notes and history. A source fingerprint marks decisions stale when their
supporting evidence changes. The fingerprint is a local change detector, not a
cryptographic document signature or lender certification.

Conversation data is held in memory by default. Storage is opt-in through the
keep-on-device checkbox. Clearing or opting out removes saved conversation data.
This browser storage is not encrypted; shared-device users should leave it off.
Exports contain the selected conversation and review notes, not the original PDF.
Untrusted excerpts, names and notes are escaped before rendering.

## Offline Boundary

The service worker precaches an exact allowlist of shell files, fonts, the chart
engine and local helper modules. It never caches API endpoints, share pages or
credential-bearing requests. Visit once while the server runs so the shell can
finish installation. A cold offline reload loads the fictional workspace; private
cases are not silently restored from the shell cache. A conversation deliberately
stored on the device can be restored separately.

The helper can explain retained evidence and existing calculations without a
server connection. New PDF/OCR operations and new loan calculations require the
backend. Fresh rates require Internet access. No chart manufactures a rate history
or fills unavailable observations with sample values.

## Public Rate Tracking

`market_tracker_v17.py` refreshes official observations and conservative lender
sources every 15 minutes while the server runs. A first snapshot request starts
the initial retrieval. Refreshes are serialized, throttled and limited to existing
public providers. Changes are recorded in basis points in process memory.
Stopping the local app stops its automatic tracking; this is not a cloud monitor.

The Bank of Canada parser selects the newest valid observation regardless of API
ordering. A combined-feed failure falls back to independent series requests.
The current five-year benchmark bond identifier is `BD.CDN.5YR.DQ.YLD`.
Failed refreshes preserve explicitly stale cached observations rather than
promoting them to live quotes. Banks with ambiguous or blocked pages remain
unverified, with direct official links.

`robots.txt` discourages compliant crawlers from accessing API, private-share
and schema paths. It is not authentication or an access-control mechanism.
This release is a local application, not an enterprise-certified public service.
