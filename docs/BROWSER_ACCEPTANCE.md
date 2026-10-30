# Browser acceptance checklist

Automated browser rendering was blocked by the execution environment's Chromium administrator navigation policy. API and server-side screen-template testing passed, but **actual cross-device screenshot QA must be repeated** before judging or public hosting.

Use Chrome/Edge/Firefox/Safari on a normal local machine with http://localhost:8000.

1. Check 390 × 844 and 1440 × 900; no horizontal document clipping except the intentionally scrollable comparison table.
2. Click all nine main-nav screens, return to Overview and verify no JavaScript console errors.
3. Upload `fixtures/fictional-renewal-letter.pdf`; balance 480000, renewal rate 5.49, 228 months, 36-month term, 2027-03-01 maturity should populate.
4. Edit rate to 5.79, blur; payment and recommendation should update without reloading.
5. Add a fixed offer and a variable offer; adjust rate, fees, amortization and comparison horizon. Confirm the charts and net cost change.
6. Change switch criteria to cash-out > 0; expected status: new underwriting. Revert to 0; conditional straight-switch signal returns for the fictional default.
7. On Rate Intelligence, check Bank of Canada observed dates. If offline, expect an unavailable warning and no invented values.
8. Check six official bank links; run the on-demand parser and inspect verification status. Never expect a personalized quote.
9. Penalty Workbench: 200000 at 6%, 36 months, simple comparable rate 4%; should return 3000 three-month interest, 12000 illustrative IRD, 12000 higher-of estimate.
10. Negotiation Coach: telephone script and email appear and are copyable.
11. Action Plan: check completed, export `.ics`, inspect that there are eight VEVENT entries.
12. Report: download PDF and open it in a PDF viewer; inspect rates and source URLs.
13. Save case, create share, open in incognito, revoke, verify link no longer works.
14. In dark theme, inspect text contrast, focus outlines and all form labels.
15. Upload an invalid PDF or 9MB file; expect an error, not an app crash.
16. With NEBIUS_API_KEY not configured, run Full Agent; verify an eight-step trace and rules-based explanation. With key configured, verify model ID, no financial hallucinations and source fidelity.
