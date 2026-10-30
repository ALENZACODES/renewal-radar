import {test} from 'node:test';
import assert from 'node:assert/strict';
import {esc,money,percent,svgChart,field,options,flag} from '../frontend/js/ui.js';
import {state,analyzeBody,resetState} from '../frontend/js/state.js';
import {getView} from '../frontend/js/views.js';
const sample={mortgage:{balance:480000,offered_rate:5.49,current_rate:4.19,
 amortization_months:228,term_months:36,maturity_date:'2027-03-01',frequency:'monthly',
 rate_type:'fixed',lender:'Fictional Bank',insurance_status:'uninsured',standalone:true,
 combined_loan_plan:false,existing_lender_federally_regulated:true,new_lender_federally_regulated:true,
 amortization_increase:false,cash_out:0,fees_financed:0,remaining_old_term_months:0},
 offers:[{name:'Competing hypothetical',rate:4.49,rate_type:'fixed',term_months:36,
 fees:850,fee_credit:0,annual_prepayment:0,monthly_extra:0,type:'hypothetical'}]};

test('esc blocks imported PDF/script HTML injection',()=>{
 const dangerous='<img src=x onerror="alert(1)">&';
 const out=esc(dangerous);
 assert.ok(!out.includes('<img'));
 assert.ok(!out.includes('"alert'));
 assert.ok(out.includes('&lt;'));
});
test('cad money formatting',()=>{
 assert.match(money(480000),/480,000/);
 assert.equal(percent(5.49),'5.49%');
});
test('forms escape imported descriptions',()=>{
 assert.ok(field('<script>','bad','<img>','text').includes('&lt;script&gt;'));
});
test('chart generates proper accessible SVG',()=>{
 const html=svgChart([{offer:{name:'Renewal'},loan:{starting_balance:480000},schedule:[{month:1,balance:479000},{month:2,balance:478000}]}]);
 assert.match(html,/role="img"/);
 assert.match(html,/Renewal/);
});
test('all nine screens and report show content without browser globals',()=>{
 resetState(sample);
 for(const p of ['overview','document','scenarios','switch','market','penalty','negotiate','plan','report']){
   state.page=p; const html=getView();
   assert.ok(html.length>120,`Empty ${p}`);
   assert.ok(html.includes('card')||html.includes('hero'),`Missing layout ${p}`);
   assert.ok(!html.includes('undefined'),`Unbound value ${p}`);
 }
});
test('analysis request includes the mortgage and alternatives',()=>{
 resetState(sample);const payload=analyzeBody();
 assert.equal(payload.mortgage.balance,480000);
 assert.equal(payload.offers[0].rate,4.49);
});
