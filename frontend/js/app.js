import {api,downloadResponse} from './api.js';
import {state,resetState,storeCase,recoverCase,analyzeBody} from './state.js';
import {esc,money,toast} from './ui.js';
import {getView} from './views.js';

const names={overview:'OVERVIEW',document:'LETTER X-RAY',scenarios:'COMPARE OFFERS',switch:'SWITCH ELIGIBILITY',market:'RATE INTELLIGENCE',penalty:'PENALTY WORKBENCH',negotiate:'NEGOTIATION COACH',plan:'ACTION PLAN',report:'STRATEGY REPORT',shared:'SHARED REPORT'};
const $=id=>document.getElementById(id);
let recalculationSeq=0;

function render(){
  $('content').innerHTML=getView();
  $('breadcrumb').textContent='YOUR MORTGAGE / '+(names[state.page]||'OVERVIEW');
  document.querySelectorAll('[data-nav]').forEach(b=>{
    const active=b.dataset.nav===state.page;
    b.classList.toggle('active',active);
    if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
  });
  document.title=`${names[state.page]||'Renewal Radar'} · Renewal Radar`;
}
function navigate(page){
  if(!state.loaded)return;
  state.page=page;
  render();
  window.scrollTo({top:0,behavior:'smooth'});
  if(page==='negotiate'&&!state.negotiation)makeNegotiation().catch(handleError);
  if(page==='penalty'&&!state.penalty)calcPenalty().catch(handleError);
}
function handleError(e){toast('⚠ '+(e?.message||'Unable to complete the operation.'));console.warn('Action failed',e?.message||e)}
async function recalculate(quiet=false){
  if(!state.mortgage)return;
  const seq=++recalculationSeq;
  try{
    const data=await api.analyze(analyzeBody());
    if(seq!==recalculationSeq)return;
    state.analysis=data;
    render();
    if(!quiet)toast('✓ Analysis refreshed using current inputs');
  }catch(e){handleError(e)}
}
async function refreshMarket(){
  try{state.market=await api.market();if(state.page==='market')render();toast(state.market?.data_status==='live-observation'?'✓ Official Bank of Canada observations updated':'Data service currently unavailable — no rates were substituted')}catch(e){handleError(e)}
}
function typed(value,field){
  if(['true','false','null'].includes(value)&&['standalone','existing_lender_federally_regulated','new_lender_federally_regulated','amortization_increase','combined_loan_plan'].includes(field))
    return value==='null'?null:value==='true';
  if(['balance','offered_rate','current_rate','amortization_months','term_months','cash_out','fees_financed','remaining_old_term_months','original_posted_rate','original_contract_discount'].includes(field))return Number(value);
  return value;
}
async function uploadDocument(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith('.pdf')){toast('Upload a PDF renewal letter.');return}
  if(file.size>8*1024*1024){toast('The PDF exceeds the 8 MB limit.');return}
  toast('Reading the renewal letter…');
  try{
    const result=await api.pdfExtract(file);
    state.document=result;
    for(const [key,evidence] of Object.entries(result.fields)){
      if(Object.hasOwn(state.mortgage,key)&&evidence.value!==null)
        state.mortgage[key]=typed(String(evidence.value),key);
    }
    await recalculate(true);
    toast(`✓ Extracted ${Object.keys(result.fields).length} fields from ${result.pages} page(s). Verify every value.`);
  }catch(e){handleError(e)}
}
async function calcPenalty(){
  let m=state.mortgage,p=state.penaltyInputs||{};
  state.penalty=await api.penalty({balance:p.balance??m.balance,current_rate:p.current_rate??m.current_rate,
    remaining_term_months:p.remaining_term_months??m.remaining_old_term_months,
    comparison_rate:p.comparison_rate??3.75, rate_type:p.rate_type??m.rate_type,
    contract_method:p.contract_method??'simple',original_posted_rate:p.original_posted_rate??5.99,
    original_discount:p.original_discount??1.25,is_open:false});
  if(state.page==='penalty')render();
}
async function makeNegotiation(){
  const input=state.negInputs||{},m=state.mortgage;
  state.negotiation=await api.negotiate({mortgage:m,competing_rate:Number(input.competing_rate??state.offers[0]?.rate??4.49),
    competing_lender:input.competing_lender??'a competing lender',goals:input.goals??'lower_interest',
    competitor_offer_verified:input.competitor_offer_verified??false});
  if(state.page==='negotiate')render();
}
async function makeInsight(){
  toast('Preparing an explanation from validated analysis…');
  state.insight=await api.insight(analyzeBody());
  render();toast(state.insight.enabled?'✓ Nemotron explanation received':'✓ Rule-based explanation prepared (AI key not configured)');
}
async function saveCase(){
  const body={title:'My renewal plan',mortgage:state.mortgage,offers:state.offers};
  if(state.caseRecord){await api.update(state.caseRecord.id,state.caseRecord.access_token,body);toast('✓ Your saved case was updated');return}
  const result=await api.save(body);storeCase(result);render();toast('✓ Case saved. Access token retained in this tab session.');
}
async function createShare(){
  if(!state.caseRecord)await saveCase();
  else await api.update(state.caseRecord.id,state.caseRecord.access_token,{title:'My renewal plan',mortgage:state.mortgage,offers:state.offers});
  const result=await api.share(state.caseRecord.id,state.caseRecord.access_token,24);
  state.shareRecord={...result,url:window.location.origin+result.url_path};
  render();toast('✓ Read-only link created; expires after 24 hours');
}
async function revokeShare(){
  if(!state.shareRecord||!state.caseRecord)return;
  await api.revokeShare(state.caseRecord.id,state.caseRecord.access_token,state.shareRecord.token);
  state.shareRecord=null;render();toast('✓ Link revoked');
}
async function downloadReport(){toast('Creating your strategy PDF…');
  const res=await api.report(analyzeBody());await downloadResponse(res,'renewal-radar-strategy.pdf');toast('✓ Report downloaded');
}
async function copyText(value){
  try{await navigator.clipboard.writeText(value);toast('✓ Copied to clipboard')}
  catch{const area=document.createElement('textarea');area.value=value;area.style.position='fixed';area.style.top='-999px';document.body.appendChild(area);area.select();document.execCommand('copy');area.remove();toast('✓ Copied')}
}
async function loadSamplePdf(){
  const response=await fetch('/api/demo/sample.pdf');if(!response.ok)throw new Error('Demo sample PDF unavailable');
  const blob=await response.blob();await uploadDocument(new File([blob],'fictional-renewal-letter.pdf',{type:'application/pdf'}));
}
async function action(name,element){
  switch(name){
    case 'run-analysis':await recalculate();break;
    case 'refresh-market':await refreshMarket();break;
    case 'load-bank-rates':state.bankRates=await api.bankRates();render();toast('✓ Official bank pages checked. Unverifiable quotes are excluded.');break;
    case 'sample-pdf':await loadSamplePdf();break;
    case 'save-case':await saveCase();break;
    case 'create-share':await createShare();break;
    case 'revoke-share':await revokeShare();break;
    case 'copy-share':if(state.shareRecord)await copyText(state.shareRecord.url);break;
    case 'copy-script':if(state.negotiation)await copyText(state.negotiation.call_script.join('\n\n'));break;
    case 'copy-email':if(state.negotiation)await copyText(state.negotiation.email);break;
    case 'make-negotiation':await makeNegotiation();toast('✓ Negotiation plan ready');break;
    case 'calc-penalty':await calcPenalty();toast('✓ Updated penalty sensitivity');break;
    case 'generate-insight':await makeInsight();break;
    case 'run-agent':toast('Agent running verified market, rules and financial tools…');state.agentRun=await api.agentRun(analyzeBody());state.insight=state.agentRun.summary;render();toast('✓ Eight-step agent run complete');break;
    case 'download-report':await downloadReport();break;
    case 'download-ledger':{const response=await api.ledger(analyzeBody());await downloadResponse(response,'renewal-radar-amortization.csv');toast('✓ Payment-by-payment CSV downloaded');break;}
    case 'download-ics':{
      const date=state.mortgage.maturity_date;
      const response=await fetch('/api/calendar/'+encodeURIComponent(date)+'.ics');
      if(!response.ok)throw new Error('Invalid maturity date');
      await downloadResponse(response,'renewal-radar-reminders.ics');toast('✓ Calendar reminders downloaded');break;
    }
    case 'open-osfi':window.open('https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/osfi-exempts-uninsured-mortgage-straight-switches-prescribed-mqr-implements-portfolio-lti-limits','_blank','noopener,noreferrer');break;
    case 'open-fcac-penalty':window.open('https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html','_blank','noopener,noreferrer');break;
    case 'add-offer':
      if(state.offers.length>=12){toast('Maximum of 12 alternatives.');break}
      state.offers.push({name:`Custom alternative ${state.offers.length+1}`,rate:4.75,rate_type:'fixed',term_months:state.horizon,amortization_months:null,fees:0,fee_credit:0,type:'hypothetical',annual_prepayment:0,monthly_extra:0,variable_path_bps:[],fixed_payment_variable:false});
      await recalculate(true);break;
    case 'remove-offer':state.offers.splice(Number(element.dataset.index),1);await recalculate(true);break;
    case 'restart-demo':await start(true);navigate('overview');toast('✓ Reset to synthetic demo');break;
    default:if(['overview','document','scenarios','switch','market','penalty','negotiate','plan','report'].includes(name))navigate(name);
  }
}

// All events are delegated so re-rendering forms never duplicates listeners.
document.addEventListener('click',e=>{
  const nav=e.target.closest('[data-nav]');
  if(nav){navigate(nav.dataset.nav);return}
  const actionButton=e.target.closest('[data-action]');
  if(actionButton){actionButton.disabled=true;Promise.resolve(action(actionButton.dataset.action,actionButton)).catch(handleError).finally(()=>{if(actionButton.isConnected)actionButton.disabled=false})}
});
document.addEventListener('change',e=>{
  const t=e.target;
  if(t.id==='pdf-upload'){uploadDocument(t.files?.[0]);t.value='';return}
  if(t.matches('.plan-check')){if(t.checked)state.checklist.add(t.dataset.id);else state.checklist.delete(t.dataset.id);render();return}
  if(t.matches('.mortgage-field')){
    const key=t.dataset.key,val=typed(t.value,key);
    if(typeof val==='number'&&!Number.isFinite(val)){toast('Enter a valid number');return}
    state.mortgage[key]=val;
    recalculate(true);return;
  }
  if(t.matches('.offer-field')){
    let i=Number(t.dataset.offerIndex),key=t.dataset.key;
    if(!state.offers[i])return;
    const v=['rate','term_months','fees','fee_credit','annual_prepayment','monthly_extra'].includes(key)?Number(t.value):t.value;
    state.offers[i][key]=v;recalculate(true);return;
  }
  if(t.matches('.analysis-field')){
    if(t.dataset.key==='horizon')state.horizon=Number(t.value);
    recalculate(true);return;
  }
  if(t.matches('.penalty-field')){
    state.penaltyInputs??={};
    state.penaltyInputs[t.dataset.key]=['rate_type','contract_method'].includes(t.dataset.key)?t.value:Number(t.value);
    calcPenalty().catch(handleError);return;
  }
  if(t.matches('.neg-field')){
    state.negInputs??={};
    state.negInputs[t.dataset.key]=t.dataset.key==='competing_rate'?Number(t.value):
      t.dataset.key==='competitor_offer_verified'?t.value==='true':t.value;
    makeNegotiation().catch(handleError);return;
  }
});
document.addEventListener('dragover',e=>{const drop=e.target.closest('#file-drop');if(drop){e.preventDefault();drop.classList.add('dragging')}});
document.addEventListener('dragleave',e=>{const drop=e.target.closest('#file-drop');if(drop)drop.classList.remove('dragging')});
document.addEventListener('drop',e=>{const drop=e.target.closest('#file-drop');if(drop){e.preventDefault();drop.classList.remove('dragging');uploadDocument(e.dataTransfer?.files?.[0])}});
$('theme-toggle').addEventListener('click',()=>{
  state.theme=state.theme==='light'?'dark':'light';document.documentElement.dataset.theme=state.theme;
  try{localStorage.setItem('rr_theme',state.theme)}catch{}
});
$('restart-demo').addEventListener('click',()=>start(true).then(()=>navigate('overview')).then(()=>toast('✓ Sample restored')).catch(handleError));

async function start(forceReset=false){
  try{
    state.theme=localStorage.getItem('rr_theme')||'light';document.documentElement.dataset.theme=state.theme;
  }catch{}
  const sharedMatch=window.location.pathname.match(/^\/shared\/([^/]+)$/);
  if(sharedMatch&&!forceReset){
    try{
      const shared=await api.readShare(sharedMatch[1]);
      state.sharedView=shared;state.loaded=true;state.page='shared';render();
    }catch(e){state.loaded=true;state.page='shared';render();handleError(e)}
    return;
  }
  if(sharedMatch&&forceReset)window.history.replaceState(null,'','/');
  const demo=await api.demo();resetState(demo);
  state.page='overview';
  render();
  const caseRecord=!forceReset?recoverCase():null;
  if(caseRecord&&window.confirm('A previous case is saved in this tab. Restore it?')){
    try{const saved=await api.load(caseRecord.id,caseRecord.access_token);
      state.mortgage=saved.data.mortgage;state.offers=saved.data.offers;storeCase(caseRecord);
    }catch{toast('Previous case no longer accessible. Loaded the sample instead.')}
  }
  const health=api.health().then(x=>{
    const el=$('api-light');el.classList.add('good');el.querySelector('span').textContent=x.ai_configured?'API · AI ready':'API connected';
  }).catch(()=>{const el=$('api-light');el.querySelector('span').textContent='Offline'});
  const analysis=recalculate(true);
  const market=api.market().then(data=>{state.market=data;if(state.page==='market')render()}).catch(()=>{});
  await Promise.allSettled([health,analysis,market]);
}
start().catch(handleError);
