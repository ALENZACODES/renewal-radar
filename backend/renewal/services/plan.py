"""Renewal checklist and portable RFC5545 reminders."""
from datetime import date,timedelta,datetime,timezone
import uuid

STEPS=[
 (120,'Review existing mortgage contract','Request maturity date, renewal terms, outstanding principal and prepayment details.'),
 (90,'Collect competing quotes','Ask qualified lenders or a licensed broker for written quotes on comparable terms.'),
 (60,'Verify switch and discharge costs','Confirm charge type, insurer transfer conditions, fees and lender underwriting.'),
 (30,'Negotiate with current lender','Use the personalized questions and seek a firm written counteroffer.'),
 (21,'Check renewal disclosure','Federally regulated lender renewal statements are generally due at least 21 days before maturity.'),
 (14,'Choose the best documented offer','Compare interest, ending balance, penalties, fees and non-rate features.'),
 (7,'Confirm signatures and funding','Verify new payment instructions and lender/solicitor documentation.'),
 (0,'Maturity day','Confirm the renewal or switch completed and retain documents.')]

def make_plan(maturity_date:str):
    d=date.fromisoformat(maturity_date)
    today=date.today()
    return [{'id':f'step-{i}','title':title,'description':description,'due':(d-timedelta(days=days)).isoformat(),
             'days_before':days,'past_due':(d-timedelta(days=days))<today,'complete':False}
            for i,(days,title,description) in enumerate(STEPS)]


def create_ics(maturity_date:str):
    events=[]
    for item in make_plan(maturity_date):
        event='\r\n'.join(['BEGIN:VEVENT',f'UID:{uuid.uuid4()}@renewalradar',
           f'DTSTAMP:{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
           f'DTSTART;VALUE=DATE:{item["due"].replace("-","")}',
           f'SUMMARY:Renewal Radar - {item["title"]}',
           'DESCRIPTION:'+item['description'].replace(',','\\,').replace(';','\\;'),
           'END:VEVENT'])
        events.append(event)
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Renewal Radar//Canada//EN\r\n'+ '\r\n'.join(events)+'\r\nEND:VCALENDAR\r\n'
