"""Polite posted-rate scraper for public lender rate pages.

Rules: robots.txt is checked first and any failure to read it means no crawl;
one request per lender per day; at least ten seconds between requests (longer
if robots.txt asks); an identifying user agent with a contact URL; no cookies,
logins or form submissions.
"""
