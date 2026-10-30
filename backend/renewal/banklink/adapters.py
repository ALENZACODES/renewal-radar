"""Provider adapters: map each aggregator's documented response shape to MortgageSnapshot.

Transports are injected. ``SandboxTransport`` replays fixture responses so the
mapping is tested without network access; no production transport is included.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from .models import LinkSession, MortgageSnapshot, Provider

D = Decimal


class Transport(Protocol):
    sandbox: bool

    def call(self, operation: str, body: dict[str, Any]) -> dict[str, Any]: ...


class ProductionNotConfigured(RuntimeError):
    pass


class SandboxTransport:
    """Returns canned responses keyed by operation name."""

    sandbox = True

    def __init__(self, responses: dict[str, dict[str, Any]]):
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, body))
        if operation not in self._responses:
            raise KeyError(f'sandbox has no response for {operation}')
        return self._responses[operation]


def _dec(value: Any) -> D | None:
    if value is None or value == '':
        return None
    try:
        return D(str(value))
    except InvalidOperation:
        return None


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _missing(s: dict[str, Any]) -> tuple[str, ...]:
    return tuple(k for k in ('balance', 'rate_pct', 'maturity_date', 'payment') if s.get(k) is None)


class BankLinkAdapter(Protocol):
    provider: Provider

    def start(self, subject: str) -> LinkSession: ...
    def exchange(self, public_token: str) -> str: ...
    def mortgages(self, access_handle: str, as_of: date) -> list[MortgageSnapshot]: ...
    def revoke(self, access_handle: str) -> None: ...


class _Base:
    provider: Provider

    def __init__(self, transport: Transport):
        if not getattr(transport, 'sandbox', False):
            raise ProductionNotConfigured(
                f'{self.provider.value} production access needs a signed provider agreement and review')
        self.t = transport


class PlaidAdapter(_Base):
    """Plaid Link + Liabilities (mortgage) in the Canadian region."""

    provider = Provider.PLAID

    def start(self, subject: str) -> LinkSession:
        r = self.t.call('link/token/create', {'user': {'client_user_id': subject},
                                               'products': ['liabilities'], 'country_codes': ['CA'],
                                               'language': 'en'})
        return LinkSession(self.provider, r['link_token'], None,
                           datetime.fromisoformat(r['expiration'].replace('Z', '+00:00')), True)

    def exchange(self, public_token: str) -> str:
        return self.t.call('item/public_token/exchange', {'public_token': public_token})['access_token']

    def mortgages(self, access_handle: str, as_of: date) -> list[MortgageSnapshot]:
        r = self.t.call('liabilities/get', {'access_token': access_handle})
        balances = {a['account_id']: a.get('balances', {}) for a in r.get('accounts', [])}
        institution = (r.get('item') or {}).get('institution_name')
        out: list[MortgageSnapshot] = []
        for m in (r.get('liabilities') or {}).get('mortgage') or []:
            rate = m.get('interest_rate') or {}
            fields = {
                'balance': _dec(balances.get(m['account_id'], {}).get('current')),
                'rate_pct': _dec(rate.get('percentage')),
                'maturity_date': _day(m.get('maturity_date')),
                'payment': _dec(m.get('next_monthly_payment')),
            }
            kind = rate.get('type')
            out.append(MortgageSnapshot(self.provider, m['account_id'], institution,
                                        fields['balance'], fields['rate_pct'],
                                        kind if kind in ('fixed', 'variable') else None,
                                        fields['maturity_date'], _day(m.get('origination_date')),
                                        fields['payment'], _dec(m.get('origination_principal_amount')),
                                        as_of, _missing(fields)))
        return out

    def revoke(self, access_handle: str) -> None:
        self.t.call('item/remove', {'access_token': access_handle})


class FlinksAdapter(_Base):
    """Flinks Connect + account detail; mortgage accounts carry balance only."""

    provider = Provider.FLINKS

    def start(self, subject: str) -> LinkSession:
        # Flinks Connect is an iframe; the app passes a per-session tag, never credentials.
        tag = secrets.token_urlsafe(16)
        return LinkSession(self.provider, tag,
                           f'https://toolbox-iframe.private.fin.ag/v2/?demo=true&tag={tag}',
                           datetime.now(timezone.utc) + timedelta(minutes=30), True)

    def exchange(self, public_token: str) -> str:
        r = self.t.call('Authorize', {'LoginId': public_token, 'MostRecentCached': True})
        return r['RequestId']

    def mortgages(self, access_handle: str, as_of: date) -> list[MortgageSnapshot]:
        r = self.t.call('GetAccountsDetail', {'RequestId': access_handle, 'WithBalance': True})
        institution = (r.get('Login') or {}).get('Institution')
        out: list[MortgageSnapshot] = []
        for a in r.get('Accounts') or []:
            label = ' '.join(str(a.get(k, '')) for k in ('Type', 'Category', 'Title')).lower()
            if 'mortgage' not in label and 'hypoth' not in label:
                continue
            balance = _dec((a.get('Balance') or {}).get('Current'))
            fields = {'balance': None if balance is None else abs(balance), 'rate_pct': None,
                      'maturity_date': None, 'payment': None}
            out.append(MortgageSnapshot(self.provider, a['Id'], institution, fields['balance'],
                                        None, None, None, None, None, None, as_of, _missing(fields)))
        return out

    def revoke(self, access_handle: str) -> None:
        self.t.call('DeleteCard', {'RequestId': access_handle})


def adapter_for(provider: Provider, transport: Transport) -> BankLinkAdapter:
    if provider is Provider.PLAID:
        return PlaidAdapter(transport)
    if provider is Provider.FLINKS:
        return FlinksAdapter(transport)
    raise ValueError(f'{provider} is not an approved provider')
