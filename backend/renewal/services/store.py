"""SQLite demo case store: opaque access credentials and expiring read-only links.

IMPORTANT: no mortgage PDF binary, bank account identifiers or name is persisted.
The store is demo/workspace functionality; production deployments must add an
identity provider, tenant policy and encryption-at-rest infrastructure.
"""
import os,json,uuid,secrets,hashlib
from datetime import datetime,timezone,timedelta
from sqlalchemy import create_engine,Column,String,DateTime,Text
from sqlalchemy.orm import DeclarativeBase,sessionmaker
from ..config import settings

class Base(DeclarativeBase):pass

class Case(Base):
    __tablename__='cases'
    id=Column(String(64),primary_key=True)
    secret_hash=Column(String(64),nullable=False)
    title=Column(String(120),nullable=False)
    payload=Column(Text,nullable=False)
    created=Column(DateTime(timezone=True),nullable=False)
    updated=Column(DateTime(timezone=True),nullable=False)

class Share(Base):
    __tablename__='shares'
    token_hash=Column(String(64),primary_key=True)
    case_id=Column(String(64),nullable=False)
    expires=Column(DateTime(timezone=True),nullable=False)

engine=create_engine(settings.database_url,connect_args={'check_same_thread':False} if settings.database_url.startswith('sqlite:') else {},pool_pre_ping=True)
Session=sessionmaker(engine,expire_on_commit=False)

def initialize():Base.metadata.create_all(engine)

def sha(value):return hashlib.sha256(value.encode()).hexdigest()

def utcnow():return datetime.now(timezone.utc)

def create_case(title,payload):
    now=utcnow();uid=str(uuid.uuid4());token=secrets.token_urlsafe(32)
    with Session() as session:
        session.add(Case(id=uid,secret_hash=sha(token),title=title,payload=json.dumps(payload),created=now,updated=now))
        session.commit()
    return {'id':uid,'access_token':token,'title':title,'created_at':now.isoformat()}

def read_case(uid,token):
    with Session() as s:
        obj=s.get(Case,uid)
        if not obj or not secrets.compare_digest(obj.secret_hash,sha(token or '')):return None
        return {'id':obj.id,'title':obj.title,'data':json.loads(obj.payload),'created_at':obj.created.isoformat()}

def update_case(uid,token,payload):
    with Session() as s:
        obj=s.get(Case,uid)
        if not obj or not secrets.compare_digest(obj.secret_hash,sha(token or '')):return False
        obj.payload=json.dumps(payload);obj.updated=utcnow();s.commit();return True

def create_share(uid,access_token,hours=24):
    with Session() as s:
        obj=s.get(Case,uid)
        if not obj or not secrets.compare_digest(obj.secret_hash,sha(access_token or '')):return None
        token=secrets.token_urlsafe(32)
        exp=utcnow()+timedelta(hours=hours)
        s.add(Share(token_hash=sha(token),case_id=uid,expires=exp));s.commit()
        return {'token':token,'expires_at':exp.isoformat()}

def read_share(token):
    with Session() as s:
        share=s.get(Share,sha(token))
        if not share or share.expires.replace(tzinfo=timezone.utc)<utcnow():return None
        obj=s.get(Case,share.case_id)
        if not obj:return None
        payload=json.loads(obj.payload)
        return {'title':obj.title,'mortgage':payload.get('mortgage'),
                'offers':payload.get('offers',[]),'shared_at':utcnow().isoformat(),
                'notice':'Read-only financial planning data. No approval or lender quote implied.'}

def revoke_share(uid,access_token,token):
    with Session() as s:
        obj=s.get(Case,uid)
        if not obj or not secrets.compare_digest(obj.secret_hash,sha(access_token or '')):return False
        share=s.get(Share,sha(token))
        if not share or share.case_id!=uid:return False
        s.delete(share);s.commit();return True
