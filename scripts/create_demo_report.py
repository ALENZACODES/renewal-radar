from pathlib import Path
from renewal.domain.schemas import Mortgage,Offer
from renewal.domain.mortgage_math import compare_offers
from renewal.domain.rules import switch_decision
from renewal.services.report import render_report
root=Path(__file__).resolve().parents[1]
m=Mortgage()
comp=compare_offers(m,[Offer(name='Illustrative alternative - not a quote',rate=4.49,term_months=36,fees=950)],36)
pdf=render_report(m,comp,switch_decision(m))
file=root/'fixtures'/'fictional-renewal-strategy.pdf'
file.write_bytes(pdf)
print(f'Created {file} ({len(pdf)} bytes)')
