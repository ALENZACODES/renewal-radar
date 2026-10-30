"""Auditable official-page rate harvesting.

No number is accepted solely because it appears near a product label. Every
promoted observation must have one unique labelled row, a permitted origin,
and a retained hash of the exact response bytes. Capture time is NOT the
historical effective date of a mortgage rate; retroactive histories require
an independent dated source.

This collector must be configured only for sources whose automated use is
permitted. Its host allowlist prevents an untrusted request from becoming SSRF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from typing import Callable, Awaitable
from urllib.parse import urlsplit, urljoin
import json
import socket

import httpx
from bs4 import BeautifulSoup

from ..intelligence.rate_history import RateArchive, RateObservation
from ..providers.bank_rates import parse_official_posted_html

MAX_HTML = 1_500_000


@dataclass(frozen=True)
class OfficialSource:
    lender: str
    url: str
    allowed_host: str
    product: str = 'Five-year closed fixed posted'
    rate_type: str = 'fixed'
    rate_kind: str = 'posted'
    term_months: int = 60
    permission_confirmed: bool = False

    def check(self) -> None:
        parts = urlsplit(self.url)
        host = (parts.hostname or '').lower().rstrip('.')
        if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None,443):
            raise ValueError('Only credential-free HTTPS source URLs are accepted')
        if host != self.allowed_host.lower().rstrip('.'):
            raise ValueError('Source must exactly match its approved host')
        if not self.permission_confirmed:
            raise ValueError('Automatic retrieval must be explicitly approved per source')
        if not self.lender.strip() or not self.product.strip():
            raise ValueError('Lender and product must be named')
        if self.rate_type != 'fixed' or self.term_months != 60 or self.rate_kind != 'posted':
            raise ValueError('This verified parser handles only five-year fixed posted rates')


def public_addresses(hostname: str, resolver: Callable | None = None) -> bool:
    """Reject private, loopback, reserved and otherwise non-global destinations."""
    try:
        if resolver is None:
            values = [entry[4][0] for entry in socket.getaddrinfo(hostname,443,type=socket.SOCK_STREAM)]
        else:
            values = resolver(hostname)
        return bool(values) and all(ip_address(value).is_global for value in values)
    except (ValueError, OSError):
        return False


def evidence_from_page(content: bytes) -> dict:
    """Decode bounded HTML and accept only a unique labelled posted-rate row."""
    if len(content) > MAX_HTML:
        return {'status':'rejected','reason':'Page exceeds maximum ingestion size'}
    try:
        html = content.decode('utf-8',errors='strict')
    except UnicodeDecodeError:
        return {'status':'rejected','reason':'Invalid UTF-8 response'}
    parsed = parse_official_posted_html(html)
    if parsed.get('value') is None:
        return {'status':'unverified','reason':parsed.get('reason','No uniquely verified rate')}
    soup = BeautifulSoup(html,'html.parser')
    title = soup.title.get_text(' ',strip=True)[:160] if soup.title else ''
    return {'status':'verified','rate':str(parsed['value']),
            'evidence':parsed['evidence'],'title':title}


@dataclass
class CollectionResult:
    lender: str
    source_url: str
    captured_at: str
    status: str
    observation_id: str | None = None
    content_sha256: str | None = None
    message: str = ''

    def as_dict(self):
        return dict(vars(self))


class OfficialRateCollector:
    def __init__(self, archive: RateArchive, *, resolver: Callable | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.archive = archive
        self.resolver = resolver
        self.transport = transport

    async def collect(self, source: OfficialSource, *, captured_at: datetime | None = None) -> CollectionResult:
        timestamp = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        outcome = CollectionResult(source.lender,source.url,timestamp,'rejected')
        try:
            source.check()
        except ValueError as exc:
            outcome.message = str(exc)
            return outcome
        if self.transport is None and not public_addresses(source.allowed_host,self.resolver):
            outcome.message='Approved hostname does not resolve exclusively to public IP addresses'
            return outcome
        # Redirects are disabled: a trusted bank domain cannot bounce us to a
        # private endpoint or a third-party source not reviewed by operators.
        try:
            async with httpx.AsyncClient(transport=self.transport,follow_redirects=False,
                                          timeout=httpx.Timeout(8),trust_env=False,
                                          headers={'User-Agent':'RenewalRadarResearch/1.0 (public sources; contact operator)'}) as client:
                async with client.stream('GET',source.url) as response:
                    if response.status_code in range(300,400):
                        outcome.message='HTTP redirect requires a separate approved source'
                        return outcome
                    response.raise_for_status()
                    mime = response.headers.get('content-type','').lower()
                    if 'text/html' not in mime:
                        outcome.message='Source was not an HTML page'
                        return outcome
                    chunks=[]
                    total=0
                    async for chunk in response.aiter_bytes():
                        total+=len(chunk)
                        if total>MAX_HTML:
                            outcome.message='Page exceeds maximum ingestion size'
                            return outcome
                        chunks.append(chunk)
            raw=b''.join(chunks)
        except httpx.HTTPError as exc:
            outcome.message=f'HTTP retrieval failed: {type(exc).__name__}'
            return outcome
        outcome.content_sha256=sha256(raw).hexdigest()
        result=evidence_from_page(raw)
        if result['status']!='verified':
            outcome.status=result['status']
            outcome.message=result['reason']
            return outcome
        observation=RateObservation(
            lender=source.lender,product=source.product,rate_type=source.rate_type,
            term_months=source.term_months,annual_rate=result['rate'],
            rate_kind=source.rate_kind,effective_at=timestamp,captured_at=timestamp,
            source_url=source.url,source_sha256=outcome.content_sha256,
            evidence=result['evidence'],provenance='official_auto_capture')
        try:
            saved=self.archive.append(observation)
        except ValueError as exc:
            outcome.message=f'Archive refused observation: {exc}'
            return outcome
        outcome.observation_id=saved['id']
        outcome.status='stored'
        outcome.message='Capture-time posted-rate observation; not a personalized quote or historical rate sheet'
        return outcome


async def collect_approved_sources(archive: RateArchive, sources: list[OfficialSource],
                                   *, collector: OfficialRateCollector | None = None) -> list[dict]:
    """Sequential collection avoids burst requests and keeps failures isolated."""
    collector=collector or OfficialRateCollector(archive)
    results=[]
    for source in sources:
        results.append((await collector.collect(source)).as_dict())
    return results


def load_source_manifest(path: str | Path) -> list[OfficialSource]:
    """Operator-reviewed JSON manifest; no arbitrary URL can be passed by a client."""
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,list) or len(data)>30:
        raise ValueError('Manifest must contain at most 30 sources')
    sources=[]
    for item in data:
        if not isinstance(item,dict):
            raise ValueError('Each source must be an object')
        source=OfficialSource(**item)
        source.check()
        sources.append(source)
    if len({s.url for s in sources}) != len(sources):
        raise ValueError('Duplicate URLs in the approved manifest')
    return sources
