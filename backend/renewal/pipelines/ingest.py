"""Idempotent scheduled data ingestion and source provenance snapshots.

Usage (hourly cron job, private worker):
PYTHONPATH=backend python -m renewal.pipelines.ingest

Official Bank of Canada observations are classified separately from unverified
bank-webpage HTML. Never promotes missing/ambiguous rates as live quotes.
"""
from __future__ import annotations
import asyncio,hashlib,json,sys
from datetime import datetime,timezone
from sqlalchemy import Column,Integer,String,Float,DateTime,Text,UniqueConstraint,select
from ..services.store import Base,engine,Session,initialize
from ..services.market import fetch_boc
from ..providers.bank_rates import fetch_bank_posted_rates

class RateObservation(Base):
    __tablename__='market_rate_observations'
    id=Column(Integer,primary_key=True,autoincrement=True)
    provider=Column(String(120),nullable=False)
    series=Column(String(100),nullable=False)
    product=Column(String(100),nullable=False)
    value=Column(Float,nullable=False)
    effective_date=Column(String(20),nullable=False)
    captured_at=Column(DateTime(timezone=True),nullable=False)
    source_url=Column(String(800),nullable=False)
    payload_hash=Column(String(64),nullable=False)
    raw_metadata=Column(Text,nullable=False)
    __table_args__=(UniqueConstraint('provider','series','effective_date','value',name='uq_observation'),)


def save_observation(provider,series,product,value,effective_date,url,meta):
    Base.metadata.create_all(engine)
    value=float(value)
    if not 0<=value<=25:raise ValueError('Out-of-range observation')
    digest=hashlib.sha256(json.dumps(meta,sort_keys=True,default=str).encode()).hexdigest()
    with Session() as session:
        found=session.scalar(select(RateObservation).where(RateObservation.provider==provider,
         RateObservation.series==series,RateObservation.effective_date==effective_date,
         RateObservation.value==value))
        if found:return False
        session.add(RateObservation(provider=provider,series=series,product=product,
            value=value,effective_date=effective_date,captured_at=datetime.now(timezone.utc),
            source_url=url,payload_hash=digest,raw_metadata=json.dumps(meta,default=str)))
        session.commit()
        return True


async def ingest_once(bank_pages:bool=True)->dict:
    report={'new_boc':0,'new_banks':0,'rejected':0,'reasons':[],'at':datetime.now(timezone.utc).isoformat()}
    bank=await fetch_boc(force=True)
    for key,obs in bank.get('series',{}).items():
        try:
            if save_observation('Bank of Canada',obs['code'],key,obs['value'],
                 obs['observed_at'],obs['source_url'],obs):report['new_boc']+=1
        except (ValueError,KeyError) as exc:
            report['rejected']+=1;report['reasons'].append(f'BoC {key}: {type(exc).__name__}')
    if bank_pages:
        for data in await fetch_bank_posted_rates():
            if not data['verified']:
                report['rejected']+=1
                report['reasons'].append(f"{data['lender']}: ambiguous or unavailable")
                continue
            if save_observation(data['lender'],'posted-five-year-fixed','5-year fixed posted',data['quote'],
                data['retrieved_at'][:10],data['source_url'],data):report['new_banks']+=1
    return report


if __name__=='__main__':
    print(json.dumps(asyncio.run(ingest_once()),indent=2))
