import pytest


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """Each test starts with an empty rate-limit window."""
    from renewal import main
    main.limiter.reset()
    yield
    main.limiter.reset()


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch, request):
    """Tests never reach lender sites: the live collector is offline unless a test patches it explicitly.
    The collector's own tests (test_ratewatch_live, review files) install their own fakes, so they are left alone."""
    from renewal.ratewatch import live
    if request.node.fspath.basename in ("test_ratewatch_live.py", "test_ratewatch_review2.py", "test_ratewatch_review3.py",
                                        "test_small_lenders.py"):
        yield
        return

    def offline(*args, **kwargs):
        raise ConnectionError("network disabled in tests")
    monkeypatch.setattr(live, "resolve", offline)
    monkeypatch.setattr(live, "market_anchor", lambda: {})
    monkeypatch.setattr(live, "board", lambda *a, **k: {})
    yield


SAMPLE_DAY = __import__("datetime").date(2026, 10, 15)


@pytest.fixture(autouse=True)
def _sample_documents_day(monkeypatch):
    """The sample contracts in these tests mature on 2027-03-01 with offers expiring 2027-02-15.
    The document readers measure days to maturity from today, so pin today to the samples' own date
    to keep results from changing as the calendar moves past those dates."""
    from datetime import date
    from renewal.ocr import contract_intelligence, contract_math_v13, contract_playbook, document_understanding

    class SampleDate(date):
        @classmethod
        def today(cls):
            return SAMPLE_DAY

    for module in (contract_intelligence, contract_math_v13, contract_playbook, document_understanding):
        monkeypatch.setattr(module, "date", SampleDate)
    yield
