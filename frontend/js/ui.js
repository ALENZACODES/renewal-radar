/** Formatting and untrusted-document XSS protection. */
export const esc = value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=(n,digits=0)=>Number.isFinite(+n)?new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD',minimumFractionDigits:digits,maximumFractionDigits:digits}).format(+n):'—';
export const percent=(n)=>Number.isFinite(+n)?`${(+n).toFixed(2)}%`:'—';
export const number=(n)=>Number.isFinite(+n)?new Intl.NumberFormat('en-CA').format(+n):'—';
export const dt=raw=>{if(!raw)return'—';try{return new Date(String(raw).slice(0,10)+'T12:00:00').toLocaleDateString('en-CA',{year:'numeric',month:'short',day:'numeric'})}catch{return esc(raw)}};
export function field(label,key,value,type='number',note='',inputClass='mortgage-field',extra=''){
  const input = type==='select'?`<select class="${inputClass}" data-key="${esc(key)}" ${extra}>${value}</select>`:
    `<input class="${inputClass}" type="${type}" data-key="${esc(key)}" value="${esc(value)}" ${type==='number'?'step="any" min="0"':''} ${extra}/>`;
  return `<div class="field"><label>${esc(label)}</label>${input}${note?`<small>${esc(note)}</small>`:''}</div>`;
}
export const options=(list,value)=>list.map(([v,n])=>`<option value="${esc(v)}"${String(value)===String(v)?' selected':''}>${esc(n)}</option>`).join('');
export const yesNoUnknown=v=>options([['true','Yes'],['false','No'],['null','Not sure']],String(v));
export function flag(text,type='neutral'){return `<span class="pill ${type}">${esc(text)}</span>`}
export function pageHead(eyebrow,title,description,actions=''){
  return `<div class="page-head"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p class="subheading">${esc(description)}</p></div>${actions?`<div class="btnrow">${actions}</div>`:''}</div>`;
}
export const button=(label,action,style='primary')=>`<button type="button" class="button ${style}" data-action="${esc(action)}">${label}</button>`;
export function svgChart(scenarios,width=760,height=240){
  if(!scenarios?.length)return'<div class="empty">No modelled scenarios yet.</div>';
  const max=Math.max(...scenarios.flatMap(s=>s.schedule.map(t=>t.balance)),1);
  const maxX=Math.max(...scenarios.flatMap(s=>s.schedule.map(t=>t.month)),1);
  const l=50,t=12,w=width-65,h=height-45,colors=['#8d9c93','#078557','#e7a44d','#7e87cc','#b971a5'];
  const axis=Array.from({length:5},(_,i)=>{let y=t+i*h/4;return `<line x1="${l}" x2="${l+w}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-dasharray="3 6"/><text x="${l-9}" y="${y+4}" font-size="10" text-anchor="end" fill="var(--muted)">${(max*(1-i/4)/1000).toFixed(0)}k</text>`}).join('');
  const xaxes=Array.from({length:4},(_,i)=>`<text x="${l+i*w/3}" y="${t+h+25}" fill="var(--muted)" font-size="10" text-anchor="middle">${Math.round(i*maxX/3)} mo</text>`).join('');
  const paths=scenarios.map((sc,i)=>{
    const pts=[{month:0,balance:sc.loan.starting_balance},...sc.schedule.filter((r,j)=>j%Math.max(1,Math.floor(sc.schedule.length/70))===0 || j===sc.schedule.length-1)];
    const path=pts.map((r,k)=>`${k?'L':'M'} ${(l+r.month/maxX*w).toFixed(1)},${(t+h-r.balance/max*h).toFixed(1)}`).join(' ');
    return `<path d="${path}" fill="none" stroke="${colors[i%colors.length]}" stroke-width="${i===0?2:3}" stroke-linecap="round" stroke-linejoin="round"/>`;
  }).join('');
  return `<div class="chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Modelled remaining mortgage balances across offer scenarios">${axis}${xaxes}${paths}</svg></div><div class="chart-legend">${scenarios.map((s,i)=>`<span><i class="legend-point" style="background:${colors[i%colors.length]}"></i>${esc(s.offer.name)}</span>`).join('')}</div>`;
}
export function stat(label,value,footer='',tone=''){
  return `<div class="card metric"><div class="metric-label">${esc(label)}</div><div class="metric-value ${tone}">${esc(value)}</div><div class="metric-foot">${footer}</div></div>`;
}
let toastTimer;
export function toast(message){const el=document.getElementById('toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),4000)}
