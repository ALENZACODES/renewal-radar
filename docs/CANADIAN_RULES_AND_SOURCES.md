# Canadian mortgage renewal sources / October 2026 reference catalogue

This is a sourced implementation note, not a guarantee that the underlying regulator has not issued later guidance. Confirm updates before production lending use.

| Rule or source | Official URL | Engine meaning |
|---|---|---|
| OSFI uninsured minimum qualifying rate | https://www.osfi-bsif.gc.ca/en/supervision/financial-institutions/banks/minimum-qualifying-rate-uninsured-mortgages | Greater of contract APR + 2 percentage points or 5.25% for most newly underwritten uninsured loans |
| OSFI uninsured straight switches | https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/osfi-exempts-uninsured-mortgage-straight-switches-prescribed-mqr-implements-portfolio-lti-limits | Effective 2024-11-21; stand-alone, FRFI to FRFI, no increased amortization or cash-out; up to $3,000 related transaction costs |
| Finance Canada insured mortgage renewal transfers | https://www.canada.ca/en/department-finance/news/2024/12/boldest-mortgage-reforms-in-decades-come-into-force-today.html | Canadian Mortgage Charter insured renewal transfer exemption; lender eligibility still applies |
| Finance Canada low-ratio portfolio insurance switches | https://www.canada.ca/en/department-finance/news/2024/12/straight-switches-and-portfolio-insurance.html | Effective insurer applications on/after 2024-12-16, original federally regulated loan stress-tested, up to $3,000 transaction costs, no equity take-out |
| FCAC mortgage renewal | https://www.canada.ca/en/financial-consumer-agency/services/mortgages/renew-mortgage.html | 21-day notice from FRFI, offer disclosure and shopping alternatives |
| FCAC prepayment charges | https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html | Lender-specific 3-month interest vs IRD methods; quotes are approximate |
| FCAC interest and amortization | https://www.canada.ca/en/financial-consumer-agency/services/mortgages/interest-on-mortgages.html | Compounding and variable-payment consumer context |
| Bank of Canada Valet | https://www.bankofcanada.ca/valet/docs/ | Official timestamped series JSON API |
| Overnight target `V39079` | https://www.bankofcanada.ca/valet/observations/V39079/json?recent=5 | Official historic observation, not mortgage quote |
| Posted five-year benchmark `V80691335` | https://www.bankofcanada.ca/valet/observations/V80691335/json?recent=5 | Aggregate/modal five-year conventional posted benchmark, not a special or quote |
| One and three year posted `V80691333,V80691334` | https://www.bankofcanada.ca/valet/observations/V80691333,V80691334/json?recent=5 | Historical bank rates |
| Prime `V80691311` | https://www.bankofcanada.ca/valet/observations/V80691311/json?recent=5 | Typical bank prime, not lender-specific spread |
| GoC five year bond `V39053` | https://www.bankofcanada.ca/valet/observations/V39053/json?recent=5 | Bond yield context, never confused with borrower rates |

**Official Big Six published-rate pages**

- RBC: https://www.rbcroyalbank.com/mortgages/mortgage-rates.html
- TD: https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates
- Scotiabank: https://www.scotiabank.com/ca/en/personal/rates-prices/mortgages-rates.html
- BMO: https://www.bmo.com/en-ca/main/personal/mortgages/mortgage-rates/
- CIBC: https://www.cibc.com/en/interest-rates/mortgage-rates.html
- National Bank: https://www.nbc.ca/personal/mortgages/rates.html

Banks are not obligated to offer one universal publicly machine-readable mortgage rate API. The included scraper only promotes an unambiguous five-year fixed **posted** HTML table entry when it can identify a term, type, posted status and single percentage. Otherwise it exposes the official source URL and verification-required status. Do not treat a posted rate as a personalized mortgage offer; conditions and rate holds differ.

**Financial modelling limitations**: This implementation uses contractual nominal/semiannual Canadian fixed compounding, and an explicitly disclosed nominal/monthly variable convention. IRD is an illustrative higher-of method, not a bank payout statement. It does not model tax deductibility or recommend a mortgage solely based on the lowest interest rate.
