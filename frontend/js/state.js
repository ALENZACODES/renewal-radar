/** Ephemeral browser-side workspace. Case access credentials saved only in sessionStorage. */
export const state={
 page:'overview', mortgage:null,offers:[],analysis:null,market:null,bankRates:null,document:null,penalty:null,
 negotiation:null,insight:null,agentRun:null,loaded:false,loading:false,caseRecord:null,shareRecord:null,
 checklist:new Set(), horizon:36,discount:4,theme:'light',sharedView:null
};
export const analyzeBody=()=>({mortgage:state.mortgage,offers:state.offers,horizon_months:state.horizon,discount_rate:state.discount,
 ...(state.penaltyInputs?.remaining_term_months>=0 ? {penalty:{balance:state.penaltyInputs.balance??state.mortgage.balance,
 current_rate:state.penaltyInputs.current_rate??state.mortgage.current_rate,
 remaining_term_months:state.penaltyInputs.remaining_term_months,
 comparison_rate:state.penaltyInputs.comparison_rate??null,
 rate_type:state.penaltyInputs.rate_type??state.mortgage.rate_type,
 contract_method:state.penaltyInputs.contract_method??'unknown',
 original_posted_rate:state.penaltyInputs.original_posted_rate??null,
 original_discount:state.penaltyInputs.original_discount??null}} : {})});
export function resetState(demo){
  Object.assign(state,{mortgage:structuredClone(demo.mortgage),offers:structuredClone(demo.offers),analysis:null,
    document:null,penalty:null,negotiation:null,insight:null,loaded:true,loading:false,caseRecord:null,shareRecord:null,checklist:new Set(),
    horizon:36,discount:4,sharedView:null});
  try{sessionStorage.removeItem('rr_case')}catch{}
}
export function storeCase(record){state.caseRecord=record;try{sessionStorage.setItem('rr_case',JSON.stringify(record))}catch{}}
export function recoverCase(){try{const data=JSON.parse(sessionStorage.getItem('rr_case'));if(data&&data.id&&data.access_token)return data}catch{}return null}
