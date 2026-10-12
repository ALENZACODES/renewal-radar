"""Posted mortgage rate history: loading, validation, as-of lookup and building.

Sources (all public, see ``data/reference/SOURCES.md``):

* Bank of Canada Valet weekly chartered-bank posted series (1-, 3-, 5-year, prime)
* Statistics Canada table 34-10-0145 monthly 5-year conventional rate
* Per-lender rates parsed from Internet Archive captures of lender rate pages
* Daily scraper output (``data/current/history.csv``)
"""
from .models import Observation, Quality, TERM_MONTHS, term_code_to_months
from .series import RateBook

__all__ = ['Observation', 'Quality', 'RateBook', 'TERM_MONTHS', 'term_code_to_months']
