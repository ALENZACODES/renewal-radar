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
    if request.node.fspath.basename in ("test_ratewatch_live.py", "test_ratewatch_review2.py", "test_ratewatch_review3.py"):
        yield
        return

    def offline(*args, **kwargs):
        raise ConnectionError("network disabled in tests")
    monkeypatch.setattr(live, "resolve", offline)
    monkeypatch.setattr(live, "market_anchor", lambda: {})
    monkeypatch.setattr(live, "board", lambda *a, **k: {})
    yield
