from renewal.pipelines.ingest import save_observation,RateObservation

def test_idempotent_snapshot():
    metadata={'v':2.25,'source':'unit test'}
    # fixed ID avoids changing the latest live data; private test store from test_api env.
    a=save_observation('TESTDATA','FIXTURE_RR_2026','fake',2.25,'2026-01-01','https://www.bankofcanada.ca/valet/docs/',metadata)
    b=save_observation('TESTDATA','FIXTURE_RR_2026','fake',2.25,'2026-01-01','https://www.bankofcanada.ca/valet/docs/',metadata)
    assert a in (True,False)
    assert b is False
