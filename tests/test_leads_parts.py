import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from renewal.leads.consent import CONSENT_TEXTS, CURRENT_VERSION, ConsentInvalid, validate_consent
from renewal.leads.identity import (Vault, duplicate_key, mask_email, mask_phone, normalize_email,
                                    normalize_phone)
from renewal.leads.scoring import LeadFacts, score_lead
from renewal.leads.webhooks import HEADER, Outbox, SignatureError, sign, verify

NOW = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
TEXT = CONSENT_TEXTS[CURRENT_VERSION]


def consent(**kw):
    base = dict(version=CURRENT_VERSION, text_digest=TEXT.digest, agreed=True,
                agreed_at=NOW - timedelta(minutes=2), contact_methods=['email'],
                brokerage='Maple Mortgage Group', now=NOW)
    base.update(kw)
    return validate_consent(**base)


def test_valid_consent():
    rec = consent(contact_methods=['phone', 'email', 'email'])
    assert rec.contact_methods == ('email', 'phone')
    assert rec.as_dict()['version'] == CURRENT_VERSION


@pytest.mark.parametrize('kw', [
    {'agreed': False}, {'agreed': 'yes'}, {'version': '2020-01'}, {'text_digest': 'x'},
    {'agreed_at': datetime(2026, 10, 12, 14)}, {'agreed_at': NOW - timedelta(hours=2)},
    {'agreed_at': NOW + timedelta(minutes=10)}, {'contact_methods': []},
    {'contact_methods': ['sms']}, {'brokerage': '  '}])
def test_invalid_consent(kw):
    with pytest.raises(ConsentInvalid):
        consent(**kw)


@pytest.mark.parametrize('raw,expected', [
    (' Jane.Doe+renewal@GMAIL.com ', 'janedoe@gmail.com'), ('a.b@googlemail.com', 'ab@gmail.com'),
    ('A.B+x@Example.ca', 'a.b+x@example.ca')])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize('raw', ['not-an-email', 'a@b', '@x.ca'])
def test_bad_email(raw):
    with pytest.raises(ValueError):
        normalize_email(raw)


@pytest.mark.parametrize('raw,expected', [('(416) 555-0199', '+14165550199'),
                                          ('1-416-555-0199', '+14165550199'), ('+1 403 555 0100', '+14035550100')])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize('raw', ['555-0199', '(016) 555-0199', '416 155 0199', '+44 20 7946 0958'])
def test_bad_phone(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_duplicate_keys_are_per_brokerage_and_keyed():
    s = b'k' * 32
    a = duplicate_key(s, email='a@x.ca', phone='+14165550199', workspace_id='w1')
    assert len(a) == 2
    assert duplicate_key(s, email='a@x.ca', phone=None, workspace_id='w2')[0] != a[0]
    assert duplicate_key(b'z' * 32, email='a@x.ca', phone=None, workspace_id='w1')[0] != a[0]
    with pytest.raises(ValueError):
        duplicate_key(s, email=None, phone=None, workspace_id='w1')


def test_vault_roundtrip_and_wrong_key():
    v = Vault(Vault.new_key())
    sealed = v.seal('secret contact')
    assert 'secret' not in sealed and v.open(sealed) == 'secret contact'
    with pytest.raises(ValueError):
        Vault(Vault.new_key()).open(sealed)


def test_masks():
    assert mask_email('janedoe@gmail.com') == 'j••••••@gmail.com'
    assert mask_phone('+14165550199') == '+1••••••0199'


def test_scoring_bands():
    hot = score_lead(LeadFacts(date(2026, 12, 1), D('600000'), D('5.89'), D('4.49'), True, True), NOW.date())
    assert hot.parts == {'timing': 40, 'savings': 30, 'readiness': 30} and hot.band == 'hot'
    warm = score_lead(LeadFacts(date(2027, 4, 1), D('300000'), D('5.00'), D('4.49'), True, False), NOW.date())
    assert warm.parts == {'timing': 25, 'savings': 10, 'readiness': 15} and warm.band == 'warm'
    cold = score_lead(LeadFacts(None, None, None, None, False, False), NOW.date())
    assert cold.score == 5 and cold.band == 'nurture'
    overdue = score_lead(LeadFacts(date(2026, 9, 1), None, None, None, False, False), NOW.date())
    assert overdue.parts['timing'] == 30


def test_sign_and_verify():
    body = b'{"a":1}'
    header = sign(b'secret', body, 1_760_000_000)
    verify(b'secret', body, header, 1_760_000_100)
    with pytest.raises(SignatureError, match='tolerance'):
        verify(b'secret', body, header, 1_760_001_000)
    with pytest.raises(SignatureError, match='mismatch'):
        verify(b'secret', b'{"a":2}', header, 1_760_000_000)
    with pytest.raises(SignatureError, match='malformed'):
        verify(b'secret', body, 'garbage', 1_760_000_000)


class Clock:
    def __init__(self):
        self.t = 1_760_000_000.0

    def __call__(self):
        return self.t


class Receiver:
    def __init__(self, codes):
        self.codes, self.seen = list(codes), []

    def post(self, url, body, headers):
        self.seen.append((url, body, headers))
        code = self.codes.pop(0)
        if isinstance(code, Exception):
            raise code
        return code


def test_outbox_delivers_signed_and_idempotent():
    clock, rx = Clock(), Receiver([200])
    box = Outbox(lambda url: b'hook-secret', rx, clock)
    d = box.enqueue('evt-1', 'https://crm.example/hook', {'type': 'lead.created'})
    assert box.enqueue('evt-1', 'https://crm.example/hook', {'type': 'other'}) is d
    box.run_due()
    assert d.status == 'delivered'
    url, body, headers = rx.seen[0]
    verify(b'hook-secret', body, headers[HEADER], int(clock.t))
    assert headers['Idempotency-Key'] == 'evt-1' and json.loads(body)['id'] == 'evt-1'
    with pytest.raises(ValueError):
        box.enqueue('evt-2', 'http://crm.example/hook', {})


def test_outbox_retries_then_dead_letters():
    clock, rx = Clock(), Receiver([503, ConnectionError(), 429, 500, 502, 500])
    box = Outbox(lambda url: b's', rx, clock)
    d = box.enqueue('evt', 'https://crm.example/hook', {})
    for wait in (0, 30, 120, 600, 3600, 21600):
        clock.t += wait
        box.run_due()
    assert d.status == 'dead' and d.attempts == 6
    assert d.history[1] == 'attempt 2: ConnectionError'


def test_outbox_client_error_is_not_retried_and_waits_for_backoff():
    clock, rx = Clock(), Receiver([400])
    box = Outbox(lambda url: b's', rx, clock)
    d = box.enqueue('evt', 'https://crm.example/hook', {})
    box.run_due()
    assert d.status == 'dead' and d.last_error == 'HTTP 400'
    clock2, rx2 = Clock(), Receiver([500, 200])
    box2 = Outbox(lambda url: b's', rx2, clock2)
    d2 = box2.enqueue('e', 'https://crm.example/hook', {})
    box2.run_due()
    clock2.t += 10
    assert box2.run_due() == []          # still backing off
    clock2.t += 25
    box2.run_due()
    assert d2.status == 'delivered'
