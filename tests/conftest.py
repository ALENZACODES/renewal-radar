import pytest


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """Each test starts with an empty rate-limit window."""
    from renewal import main
    main.limiter.reset()
    yield
    main.limiter.reset()
