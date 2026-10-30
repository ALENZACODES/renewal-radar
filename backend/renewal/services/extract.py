"""PDF evidence extraction: page-indexed, bounded, no uploaded bytes saved."""
from __future__ import annotations
import re
from pathlib import Path
import fitz
from ..domain.schemas import FieldEvidence, Extraction

PATTERNS = {
 'balance': [r'(?:outstanding\s+)?(?:mortgage\s+)?(?:principal\s+)?balance(?:\s+at\s+renewal)?\s*[:$]?\s*\$?([\d,]+(?:\.\d{1,2})?)',r'amount\s+owing\s*:?\s*\$?([\d,]+(?:\.\d{1,2})?)'],
 'offered_rate':[r'(?:renewal\s+offer|renewal\s+(?:interest\s+)?rate|offered\s+(?:interest\s+)?rate|new\s+interest\s+rate)\s*:?\s*([\d.]+)\s*%', r'(?:interest\s+rate)\s*:?\s*([\d.]+)\s*%'],
 'current_rate':[r'current\s+(?:interest\s+)?rate\s*:?\s*([\d.]+)\s*%'],
 'term_months':[r'(?:renewal\s+)?term\s*:?\s*(\d+)\s*months?', r'(?:renewal\s+)?term\s*:?\s*(\d+)\s*years?'],
 'amortization_months':[r'(?:remaining\s+)?amorti[sz]ation(?:\s+period)?\s*:?\s*(\d+)\s*years?(?:\s*(\d+)\s*months?)?',
       r'(?:remaining\s+)?amorti[sz]ation(?:\s+period)?\s*:?\s*(\d+)\s*months?'],
 'maturity_date':[r'(?:maturity|renewal|expiry|expiration)\s+date\s*:?\s*(\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})'],
 'frequency':[r'(?:payment\s+)?frequency\s*:?\s*(monthly|semi-monthly|biweekly|bi-weekly|weekly)',r'payments?\s+(monthly|semi-monthly|biweekly|bi-weekly|weekly)'],
}


def normalize(k:str,match:re.Match,pattern_index:int):
    val=match.group(1)
    if k in ('balance','offered_rate','current_rate'):
        amount=float(val.replace(',',''))
        return amount if ((0 < amount <= 100000000) if k=='balance' else (0 < amount <=30)) else None
    if k=='term_months':
        v=int(val)*(12 if 'year' in match.group(0).lower() else 1)
        return v if 1<=v<=120 else None
    if k=='amortization_months':
        v=int(val) *(12 if 'year' in match.group(0).lower() else 1)
        if match.lastindex and match.lastindex >= 2 and match.group(2):v+=int(match.group(2))
        return v if 1<=v<=480 else None
    if k=='frequency':return val.lower().replace('bi-weekly','biweekly')
    if k=='maturity_date':
        from datetime import datetime
        for fmt in ('%Y-%m-%d','%B %d, %Y','%B %d %Y','%b %d, %Y','%b %d %Y','%m/%d/%Y','%d/%m/%Y'):
            try:return datetime.strptime(val,fmt).date().isoformat()
            except ValueError:pass
        return None
    return val


def extract_pdf(data: bytes, filename: str, max_pages:int=16) -> Extraction:
    if not data.startswith(b'%PDF-'):
        raise ValueError('Upload must be a valid PDF document.')
    if len(data)>8*1024*1024:
        raise ValueError('The PDF exceeds the 8 MB limit.')
    try:
        doc=fitz.open(stream=data,filetype='pdf')
    except Exception as exc:
        raise ValueError('Unable to open this PDF.') from exc
    try:
        if doc.needs_pass:
            raise ValueError('Password-protected PDFs cannot be read; export an unlocked copy locally.')
        if doc.page_count<1 or doc.page_count>max_pages:
            raise ValueError(f'PDF must contain between 1 and {max_pages} pages.')
        fields={}
        pages=[]
        for page_idx,page in enumerate(doc):
            text=page.get_text(sort=True)[:18000]
            # Preserve preview with safe bounded length. No HTML injection in client.
            pages.append({'page':page_idx+1,'text':text[:2600]})
            # Capture data even in table-style multiple lines, but prefer field-specific matches.
            flattened=re.sub(r'\s+',' ',text)
            for key, patterns in PATTERNS.items():
                if key in fields:continue
                for p_index, pattern in enumerate(patterns):
                    found=re.search(pattern,flattened,re.I)
                    if not found:continue
                    value=normalize(key,found,p_index)
                    if value is None:continue
                    excerpt=flattened[max(0,found.start()-65):min(len(flattened),found.end()+70)]
                    fields[key]=FieldEvidence(value=value,page=page_idx+1,excerpt=excerpt,confidence='high' if p_index==0 else 'medium')
                    break
        warnings=[]
        for required in ('balance','offered_rate','amortization_months','maturity_date'):
            if required not in fields: warnings.append(f'Could not confidently identify {required.replace("_"," ")}; please enter it manually.')
        if not any(p['text'].strip() for p in pages):
            warnings.append('This appears to be an image-only scan. A text-searchable PDF is needed for automatic extraction; fields can be entered manually.')
        return Extraction(fields=fields,pages=doc.page_count,filename=Path(filename).name[:120],warnings=warnings,preview=pages)
    finally:
        doc.close()
