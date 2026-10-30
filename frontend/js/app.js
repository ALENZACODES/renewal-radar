import {api,downloadResponse} from './api.js';
import {state,resetState,storeCase,recoverCase,analyzeBody,legacyPenaltyMethod} from './state.js';
import {esc,money,toast} from './ui.js';
import {getView} from './views.js';
import {mountLocalMortgageHelper} from './helper-panel.js';
import {loadInitialWorkspace,registerOfflineShell} from './offline-workspace.js';
import {RateRefreshController} from './rate-tracker.js';
import {mountMortgageCharts} from './chart-runtime.js';
import {timelineRequest,exitCostExample} from './penalty-studio.js';
import {lenderExactRequest} from './lender-exact.js';
import {bookReviewRequest} from './broker-book.js';

const names={overview:'OVERVIEW',document:'LETTER X-RAY',scenarios:'COMPARE OFFERS',switch:'SWITCH ELIGIBILITY',market:'RATE INTELLIGENCE',penalty:'PENALTY WORKBENCH',negotiate:'NEGOTIATION COACH',plan:'ACTION PLAN',report:'STRATEGY REPORT',shared:'SHARED REPORT'};
const $=id=>document.getElementById(id);
let recalculationSeq=0;
let documentUploadSeq=0;
let penaltySeq=0;

function render(){
  const penaltyInputsOpen=document.getElementById('penalty-inputs')?.open;
  if(penaltyInputsOpen!==undefined)state.penaltyInputsOpen=penaltyInputsOpen;
  $('content').innerHTML=getView();
  $('breadcrumb').textContent='YOUR MORTGAGE / '+(names[state.page]||'OVERVIEW');
  document.querySelectorAll('[data-nav]').forEach(b=>{
    const active=b.dataset.nav===state.page;
    b.classList.toggle('active',active);
    if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
  });
  document.title=`${names[state.page]||'Renewal Radar'} · Renewal Radar`;
  localHelper.refresh();
  mortgageCharts.refresh();
}
function navigate(page){
  if(!state.loaded)return;
  state.page=page;
  document.getElementById('mobile-more')?.removeAttribute('open');
  render();
  window.scrollTo({top:0,behavior:'smooth'});
  if(page==='negotiate'&&!state.negotiation)makeNegotiation().catch(handleError);
  if(page==='penalty'&&!state.penaltyTimeline)calcPenalty().catch(handleError);
  if(page==='live'&&!state.liveRates)loadLiveRates(false).catch(handleError);
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
  const snapshot=await rateRefresh.refresh(true);
  toast(snapshot?.data_status==='live-observation'?'Official observations refreshed':'Rates are cached or unavailable. Check the source status.');
}
function typed(value,field){
  if(['true','false','null'].includes(value)&&['standalone','existing_lender_federally_regulated','new_lender_federally_regulated','amortization_increase','combined_loan_plan'].includes(field))
    return value==='null'?null:value==='true';
  if(['balance','offered_rate','current_rate','amortization_months','term_months','cash_out','fees_financed','remaining_old_term_months','original_posted_rate','original_contract_discount'].includes(field))return Number(value);
  return value;
}
async function uploadDocument(file){
  if(!file)return;
  if(!/\.(pdf|png|jpe?g|webp|tiff?)$/i.test(file.name)){toast('Upload a PDF or document image.');return}
  if(file.size>8*1024*1024){toast('The PDF exceeds the 8 MB limit.');return}
  const uploadSeq=++documentUploadSeq;
  toast('Reading the document locally. Scanned pages may take longer.');
  try{
    const result=await api.documentRead(file,state.ocrLanguage||'eng');
    if(uploadSeq!==documentUploadSeq)return;
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
  const sequence=++penaltySeq;
  let m=state.mortgage,p=state.penaltyInputs||{};
  const results=await Promise.allSettled([api.penalty({balance:p.balance??m.balance,current_rate:p.current_rate??m.current_rate,
    remaining_term_months:p.remaining_term_months??m.remaining_old_term_months,
    comparison_rate:p.comparison_rate??3.75, rate_type:p.rate_type??m.rate_type,
    contract_method:legacyPenaltyMethod(timelineRequest(state).method),original_posted_rate:p.original_posted_rate??null,
    original_discount:p.original_discount===''?null:p.original_discount??null,is_open:false}),api.penaltyTimeline(timelineRequest(state))]);
  if(sequence!==penaltySeq)return;
  if(results[0].status==='fulfilled')state.penalty=results[0].value;
  if(results[1].status==='fulfilled'){state.penaltyTimeline=results[1].value;state.penaltyTimelineError=null;}
  else {state.penaltyTimeline=null;state.penaltyTimelineError=results[1].reason?.message||'Timeline unavailable';}
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
async function loadSampleScan(){
  const response=await fetch('/api/demo/sample-scan.png');
  if(!response.ok)throw new Error('RBC illustration scan is unavailable');
  const blob=await response.blob();await uploadDocument(new File([blob],'rbc-renewal-illustration.png',{type:'image/png'}));
}
async function action(name,element){
  switch(name){
    case 'run-analysis':await recalculate();break;
    case 'refresh-market':await refreshMarket();break;
    case 'load-bank-rates':state.bankRates=await api.bankRates();render();toast('✓ Official bank pages checked. Unverifiable quotes are excluded.');break;
    case 'sample-pdf':await loadSamplePdf();break;
    case 'sample-scan':await loadSampleScan();break;
    case 'save-case':await saveCase();break;
    case 'create-share':await createShare();break;
    case 'revoke-share':await revokeShare();break;
    case 'copy-share':if(state.shareRecord)await copyText(state.shareRecord.url);break;
    case 'copy-script':if(state.negotiation)await copyText(state.negotiation.call_script.join('\n\n'));break;
    case 'copy-email':if(state.negotiation)await copyText(state.negotiation.email);break;
    case 'make-negotiation':await makeNegotiation();toast('✓ Negotiation plan ready');break;
    case 'calc-penalty':await calcPenalty();toast('✓ Updated penalty sensitivity');break;
    case 'lender-exact-calc':await lenderExactCalc();break;
    case 'book-review':await runBookReview();break;
    case 'book-export':{if(!state.bookImport?.deals?.length){toast('Import deals first');break;}const response=await api.bookReviewCsv(bookReviewRequest(state.bookImport.deals,state.bookFilters));await downloadResponse(response,'book-opportunities.csv');break;}
    case 'book-sample':{const response=await api.bookSample();await downloadResponse(response,'broker-book-sample.csv');break;}
    case 'live-rates-refresh':toast('Checking every lender…');await loadLiveRates(true);toast('✓ Rates refreshed');break;
    case 'lender-exact-letter':{const lx={...(state.lenderExact||{})};const response=await api.ratewatchLetter({...lenderExactRequest(lx),client_name:lx.client_name||'Homeowner',language:lx.language||'en'});await downloadResponse(response,'penalty-assessment.pdf');toast('✓ Letter downloaded');break;}
    case 'lender-exact-csv':{const response=await api.ratewatchExtra('csv',lenderExactRequest(state.lenderExact));await downloadResponse(response,'penalty.csv');break;}
    case 'penalty-example':state.penaltyInputs=exitCostExample();state.penaltyExample=true;state.penaltyMonth=0;await calcPenalty();break;
    case 'penalty-workspace':state.penaltyInputs=null;state.penaltyExample=false;state.penaltyMonth=0;await calcPenalty();break;
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
async function runBookReview(){
  if(!state.bookImport?.deals?.length){state.bookError='Import a file of deals first.';render();return;}
  state.bookError=null;
  try{state.bookReview=await api.bookReview(bookReviewRequest(state.bookImport.deals,state.bookFilters));}
  catch(err){state.bookError=err.message;}
  render();
}
async function loadLiveRates(force){
  state.liveRatesError=null;
  try{state.liveRates=force?await api.liveRatesRefresh():await api.liveRates();}
  catch(err){state.liveRatesError=err.message;}
  render();
}
async function lenderExactCalc(){
  const body=lenderExactRequest(state.lenderExact);
  state.lenderExactError=null;
  try{
    state.lenderExactResult=await api.ratewatchPenalty(body);
    const matured=state.lenderExactResult.method==='matured';
    state.lenderExactForecast=matured?null:await api.ratewatchForecast(body);
    state.lenderExactCheapest=matured?null:await api.ratewatchExtra('cheapest-day',body);
  }catch(err){state.lenderExactResult=null;state.lenderExactError=err.message;}
  render();
}
document.addEventListener('click',e=>{
  const nav=e.target.closest('[data-nav]');
  if(nav){navigate(nav.dataset.nav);return}
  const actionButton=e.target.closest('[data-action]');
  if(actionButton){actionButton.disabled=true;Promise.resolve(action(actionButton.dataset.action,actionButton)).catch(handleError).finally(()=>{if(actionButton.isConnected)actionButton.disabled=false})}
});
document.addEventListener('change',e=>{
  const t=e.target;
  if(t.matches('.document-language')){state.ocrLanguage=t.value;return;}
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
  if(t.matches('.book-filter')){
    state.bookFilters??={};
    state.bookFilters[t.dataset.key]=t.value;
    return;
  }
  if(t.matches('.book-file')&&t.files?.[0]){
    state.bookError=null;
    api.bookImport(t.files[0]).then(r=>{state.bookImport=r;state.bookReview=null;return runBookReview();})
      .catch(err=>{state.bookError=err.message;render();});
    return;
  }
  if(t.matches('.book-ocr')&&t.files?.length){
    state.bookError=null;toast('Reading documents locally…');
    api.bookOcr([...t.files]).then(r=>{
      const prior=state.bookImport?.deals||[];
      state.bookImport={deals:[...prior,...r.deals],with_issues:r.deals.length,mapping:null};
      if(r.errors?.length)state.bookError=r.errors.map(e=>`${e.file}: ${e.error}`).join(' · ');
      return runBookReview();
    }).catch(err=>{state.bookError=err.message;render();});
    return;
  }
  if(t.matches('.lx-field')){
    state.lenderExact??={};
    state.lenderExact[t.dataset.key]=t.value;
    return;
  }
  if(t.matches('.penalty-field')){
    state.penaltyInputs??={};
    state.penaltyInputs[t.dataset.key]=t.type==='checkbox'?t.checked:t.value;
    calcPenalty().catch(handleError);return;
  }
  if(t.matches('.penalty-ladder-rate')){
    state.penaltyInputs??={};
    state.penaltyInputs.ladder??=[6,12,24,36,48,60].map(months=>({months,rate:''}));
    state.penaltyInputs.ladder[Number(t.dataset.index)].rate=t.value;
    calcPenalty().catch(handleError);return;
  }
  if(t.matches('.penalty-month')){
    state.penaltyMonth=Number(t.value);render();
    document.querySelector('.penalty-month')?.focus({preventScroll:true});return;
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
  mortgageCharts.refresh();
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
  const initial=await loadInitialWorkspace(api);resetState(initial.data);
  state.offlineWorkspace=initial.offline;
  state.page='overview';
  render();
  const caseRecord=!forceReset&&!initial.offline?recoverCase():null;
  if(caseRecord&&window.confirm('A previous case is saved in this tab. Restore it?')){
    try{const saved=await api.load(caseRecord.id,caseRecord.access_token);
      state.mortgage=saved.data.mortgage;state.offers=saved.data.offers;storeCase(caseRecord);
    }catch{toast('Previous case no longer accessible. Loaded the sample instead.')}
  }
  const health=api.health().then(x=>{
    const el=$('api-light');el.classList.add('good');el.querySelector('span').textContent=x.ai_configured?'API · AI ready':'API connected';
  }).catch(()=>{const el=$('api-light');el.querySelector('span').textContent='Offline'});
  const analysis=initial.offline?Promise.resolve():recalculate(true);
  const market=initial.offline?Promise.resolve():rateRefresh.refresh();
  await Promise.allSettled([health,analysis,market]);
}
const localHelper=mountLocalMortgageHelper({getWorkspace:()=>state});
const mortgageCharts=mountMortgageCharts($('content'),()=>state);
const rateRefresh=new RateRefreshController({fetchSnapshot:()=>api.rateSnapshot(),forceRefresh:()=>api.rateRefresh(),
  onUpdate:snapshot=>{state.rateTracking=snapshot;state.market=snapshot.market;state.bankRates={bank_rates:snapshot.banks};
    if(state.page==='market')render();else localHelper.refresh();},
  onError:()=>{if(state.market?.series){state.market={...state.market,data_status:'cached-stale',from_cache:true};
    if(state.rateTracking)state.rateTracking={...state.rateTracking,data_status:'cached-stale'};
    if(state.page==='market')render();else localHelper.refresh();}}});
registerOfflineShell();
rateRefresh.start();
start().catch(handleError);
