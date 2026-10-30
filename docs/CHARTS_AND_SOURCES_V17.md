# V17 Typography, Charts And GitHub Sources

## Font Selection

There is no universal measurable 'most liked' font. The choice uses public
adoption signals, screen readability, licensing and the requested Canada-inspired
style. Inter's primary repository showed approximately 20,000 GitHub stars during
research; that signal is not a ranking of every typeface or a quality guarantee.

- Lato: Canada-inspired base headings, local Regular and Bold files; SIL Open Font License.
- Noto Sans: body text, local variable font; SIL Open Font License.
- Inter 4.1: final interface headings, financial metrics and chart labels, local WOFF2 variable font;
  SIL Open Font License. Tabular numerals keep changing numbers aligned.

The Government of Canada specifies Lato and Noto Sans in its typography guidance:
https://design.canada.ca/styles/typography.html
The final naval/academic override follows the user's later Penn Engineering
reference: https://www.engineering.upenn.edu/. The observed reference uses TWK
Everett, a proprietary font which is not redistributed here. Inter is the free,
bundled alternative; Georgia/system serif styles the product wordmark. Crimson
headings, navy navigation, white space and original restrained waves carry the
requested visual direction. Penn's seal, wordmark, photographs and font files
are not copied, and no university affiliation is claimed.

The app retains its own Renewal Radar branding and does not display a government
seal or claim endorsement. Inter complements the data surfaces, not the official
Canada.ca brand system. No external font request is needed at runtime.

Primary font sources and licenses:

- https://github.com/rsms/inter/releases/tag/v4.1
- https://github.com/rsms/inter/blob/v4.1/docs/font-files/InterVariable.woff2
- https://github.com/rsms/inter/blob/v4.1/LICENSE.txt
- https://github.com/google/fonts/tree/main/ofl/lato
- https://github.com/google/fonts/tree/main/ofl/notosans
- https://github.com/latofonts/lato-source

## Chart Engine

Apache ECharts 6.1.0 was checked against its official latest GitHub release and
Apache release metadata. The unmodified distribution, Apache LICENSE and NOTICE
are included in `frontend/assets/vendor`. The app-specific data preparation,
option builders, accessible tables and lifecycle controller are original additions.
Imported vendor code and fonts are not used to satisfy the functional line target.

- https://github.com/apache/echarts/releases/tag/6.1.0
- https://github.com/apache/echarts/blob/6.1.0/dist/echarts.min.js
- https://github.com/apache/echarts/blob/6.1.0/LICENSE
- https://github.com/apache/echarts/blob/6.1.0/NOTICE
- https://release-catalog.apache.org/echarts/6.1.0/index.html
- https://apache.github.io/echarts-handbook/en/best-practices/aria/

## Financial Meaning

`chart-data.js` rejects invalid values and prepares bounded datasets without
changing the mortgage engine. Debt curves use the starting principal and actual
payment ledger points. Cumulative interest is the sum of ledger interest, not the
sum of payments. Curves stop when the modelled term stops; they are never extended
through an unknown future renewal rate. Shorter terms are labelled explicitly.

Comparable cost bars use interest plus net fees. The backend's reconciliation is:

    net cost = total paid + ending principal - starting principal + net fees
             = total interest + net fees

The chart rejects inconsistent aggregates instead of disguising a discrepancy.
Fee credits remain negative. Shorter-than-horizon terms are excluded from this
cost chart, just as the backend excludes them from a common-horizon ranking.
Payment savings and interest savings must not be added together.

The public-rate landscape shows six distinct benchmarks on a shared zero-based
percentage axis. It is a snapshot, not a historical trend or a forecast. Each
observation remains available with its publication date and official series code
in a table. Missing data is omitted, not substituted with mortgage demo inputs.
Only validated Bank of Canada source URLs are accepted for this chart.

Primary data sources:

- https://www.bankofcanada.ca/valet/docs/
- https://www.bankofcanada.ca/rates/interest-rates/lookup-bond-yields/
- https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json?recent=2
- https://www.canada.ca/en/financial-consumer-agency/services/mortgages/renew-mortgage.html

## Accessibility And Runtime

Charts use SVG rendering, rich-text tooltips, distinct colour families, visible
series labels, accessible data tables, reduced-motion support and stable heights.
Balance/interest modes are ordinary keyboard-compatible buttons with selected
state. Chart downloads produce local SVGs. A ResizeObserver adapts to layout
changes, and old charts/listeners are disposed across page renders.

All assets are in the offline shell allowlist. The chart engine does not download
code or data from a CDN. Financial calculations still use the audited backend;
ECharts only presents the resulting numbers. Test coverage includes malformed
data, fee credits, shorter terms, dates, source validation, escaped names, lifecycle
disposal, mode state and actual server-side SVG rendering with the bundled engine.
