/** All actions target the same-origin FastAPI server; secrets stay server-side. */
async function request(path,options={}){
  const res=await fetch(path,{...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(options.headers||{})},cache:'no-store'});
  if(!res.ok){let message=`Request failed (${res.status})`;try{const err=await res.json();message=typeof err.detail==='string'?err.detail:JSON.stringify(err.detail)}catch{}throw new Error(message)}
  const ct=res.headers.get('content-type')||'';
  return ct.includes('application/json')?res.json():res;
}
export const api={
  health:()=>request('/api/health'), demo:()=>request('/api/demo'),
  market:()=>request('/api/market'), bankRates:()=>request('/api/market/banks/live'),
  analyze:(body)=>request('/api/analyze',{method:'POST',body:JSON.stringify(body)}),
  penalty:(body)=>request('/api/penalty',{method:'POST',body:JSON.stringify(body)}),
  negotiate:(body)=>request('/api/negotiation',{method:'POST',body:JSON.stringify(body)}),
  insight:(body)=>request('/api/agent/insight',{method:'POST',body:JSON.stringify(body)}),
  agentRun:(body)=>request('/api/agent/run',{method:'POST',body:JSON.stringify(body)}),
  pdfExtract:(file)=>{const form=new FormData();form.append('file',file);return request('/api/documents/extract',{method:'POST',body:form})},
  ledger:(body)=>request('/api/ledger.csv',{method:'POST',body:JSON.stringify(body)}),
  annual:(body)=>request('/api/ledger/annual',{method:'POST',body:JSON.stringify(body)}),
  report:(body)=>request('/api/report/pdf',{method:'POST',body:JSON.stringify(body)}),
  save:(body)=>request('/api/cases',{method:'POST',body:JSON.stringify(body)}),
  update:(id,token,body)=>request(`/api/cases/${encodeURIComponent(id)}`,{method:'PUT',headers:{'X-Case-Token':token},body:JSON.stringify(body)}),
  load:(id,token)=>request(`/api/cases/${encodeURIComponent(id)}`,{headers:{'X-Case-Token':token}}),
  share:(id,token,hours)=>request(`/api/cases/${encodeURIComponent(id)}/share`,{method:'POST',headers:{'X-Case-Token':token},body:JSON.stringify({expires_hours:hours})}),
  readShare:(token)=>request('/api/shares/'+encodeURIComponent(token)),
  revokeShare:(id,access,token)=>request(`/api/cases/${encodeURIComponent(id)}/shares/${encodeURIComponent(token)}`,{method:'DELETE',headers:{'X-Case-Token':access}})
};
export async function downloadResponse(response,filename){
  const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');
  a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
}
