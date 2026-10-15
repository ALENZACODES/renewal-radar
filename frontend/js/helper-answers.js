import {classifyHelperQuestion, normalizeHelperQuestion} from './helper-classifier.js';
import {helperTopics, helperModelVersion} from './helper-model.js';
import {safeHelperContext, findHelperFact, helperFactEvidence, helperCheckEvidence, requestedHelperScopes, helperFingerprint} from './helper-context.js';

const money = value => new Intl.NumberFormat('en-CA', {style: 'currency', currency: 'CAD'}).format(value);
const scopeNames = {original: 'original mortgage', renewal: 'renewal offer', payout: 'payout statement', unspecified: 'document', workspace: 'workspace input'};
const fieldLabels = {
  contract_rate: 'contract rate', posted_rate: 'posted rate', contract_discount: 'contract discount',
  offered_rate: 'offered renewal rate', current_rate: 'current interest rate',
  mortgage_start_date: 'mortgage start date', maturity_date: 'maturity date',
  term_start_date: 'term start date', renewal_date: 'renewal date',
  offer_expiry_date: 'offer expiry date', term_months: 'term',
  amortization_months: 'remaining amortization', balance: 'mortgage balance',
  payment_amount: 'regular payment', frequency: 'payment frequency',
};
const definitions = {
  contract_rate: 'The contract rate is the interest rate stated in the mortgage agreement. It can differ from a newly offered renewal rate.',
  posted_rate: 'A posted rate is a lender advertised rate. The posted rate at origination and a current comparison rate are different inputs.',
  discount: 'A contract discount is usually expressed in percentage points from the relevant posted rate, not as a percentage reduction of the rate itself.',
  mortgage_date: 'The original funding or advance date anchors the original mortgage. It does not automatically start a later renewal term.',
  renewal_date: 'A renewal date, new term effective date, and original mortgage funding date should be recorded separately.',
  maturity: 'Maturity is the end of the stated contract term. An offer acceptance deadline may be earlier.',
  term: 'The term is how long the mortgage contract and its conditions stay in effect. It is different from the repayment horizon.',
  amortization: 'Amortization is the estimated time to repay the mortgage under the payment assumptions. A mortgage can pass through several terms during that period.',
  renewal_rate: 'A renewal offer describes proposed new terms. It does not establish the rate used for an early-payout penalty.',
  current_rate: 'The current rate belongs to the existing loan. Confirm whether the contract describes it as fixed, variable, or discounted.',
  balance: 'The outstanding principal is separate from the original loan amount and from a payout total that may include fees or accrued interest.',
  payment: 'A regular payment may include principal, interest, property taxes, or insurance. Compare the same components and payment frequency.',
  expiry: 'The offer expiry is an acceptance deadline. It is not automatically the mortgage maturity or term start date.',
};

function formatFact(fact) {
  const value = fact.value;
  if (fact.field.includes('rate')) return `${value}%`;
  if (fact.field === 'contract_discount') return `${value} percentage points`;
  if (fact.field === 'balance' || fact.field === 'payment_amount') return money(value);
  if (fact.field.endsWith('_months')) {
    const years = Math.floor(value / 12);
    const months = value % 12;
    return `${value} months${years ? ` (${years} year${years === 1 ? '' : 's'}${months ? ` and ${months} months` : ''})` : ''}`;
  }
  return fact.field.endsWith('_date') ? String(value) : String(value).replaceAll('-', ' ');
}

function fieldClaim(context, field, scopes) {
  const fact = findHelperFact(context, field, scopes);
  const label = fieldLabels[field] || field.replaceAll('_', ' ');
  if (!fact) return {text: `I cannot find the ${label} in the available evidence.`, status: 'missing', evidence: [], field};
  const evidence = helperFactEvidence(context, fact);
  if (fact.status === 'conflict') {
    return {text: `The ${label} has conflicting values. Check the source passages before selecting a number.`, status: 'conflict', evidence, field};
  }
  if (fact.status === 'review' || fact.status === 'unreadable' || fact.value === null) {
    return {text: `The ${label} needs confirmation; I will not use it as a confirmed value.`, status: 'review', evidence, field};
  }
  if (fact.scope === 'unspecified') {
    return {text: `The document shows ${label}: ${formatFact(fact)}, but its term context needs confirmation.`, status: 'review', evidence, field};
  }
  const source = fact.source === 'workspace' ? 'Your current workspace input' : `The ${scopeNames[fact.scope]}`;
  return {text: `${source} has ${label}: ${formatFact(fact)}.`, status: fact.source === 'workspace' ? 'input' : 'evidence', evidence, field};
}

function claimsForFields(context, fields, scopes) {
  return fields.map(field => fieldClaim(context, field, scopes));
}

function discountClaims(context, scopes) {
  const claims = claimsForFields(context, ['posted_rate', 'contract_rate', 'contract_discount'], scopes);
  const facts = ['posted_rate', 'contract_rate', 'contract_discount'].map(field => findHelperFact(context, field, scopes));
  if (facts.every(fact => fact && fact.status === 'resolved' && fact.scope !== 'unspecified')
      && new Set(facts.map(fact => fact.scope)).size === 1) {
    const [posted, contract, discount] = facts.map(fact => Math.round(fact.value * 1000));
    const expected = (posted - contract) / 1000;
    const matches = posted >= contract && Math.abs(posted - contract - discount) <= 5;
    claims.push({
      text: `${facts[0].value}% - ${facts[1].value}% = ${expected} percentage points (${Math.round(expected * 100)} basis points). ${matches ? 'This matches the stated discount.' : 'This does not match the stated discount; ask the lender to confirm the inputs.'}`,
      status: matches ? 'calculation' : 'conflict',
      evidence: facts.flatMap(fact => helperFactEvidence(context, fact)),
      field: 'contract_discount',
    });
  } else {
    claims.push({text: 'A discount calculation needs three confirmed rates from the same term. Missing or conflicting rates cannot be substituted.', status: 'missing', evidence: []});
  }
  return claims;
}

function irdClaims(context) {
  const clauses = context.clauses.filter(clause => clause.topic === 'ird');
  const evidence = clauses.map(clause => context.ledger[clause.id]).filter(Boolean);
  const assertions = new Set(clauses.map(clause => clause.assertion));
  let text;
  let status = 'review';
  if (!clauses.length) {
    text = 'I cannot find an IRD clause in the available document evidence. This does not mean the penalty is zero.';
    status = 'missing';
  } else if (assertions.has('mentioned') && assertions.has('negated')) {
    text = 'The document both mentions and negates IRD. Confirm which clause and conditions apply.';
    status = 'conflict';
  } else if (assertions.size === 1 && assertions.has('negated')) {
    text = 'The recorded wording negates IRD. It does not establish that every discharge fee is waived.';
  } else if (assertions.size === 1 && assertions.has('example')) {
    text = 'IRD appears only in an example. Locate the operative penalty clause before using it.';
  } else {
    text = 'IRD wording is present. A condition such as early discharge can limit when it applies.';
  }
  const claims = [{text, status, evidence}];
  const inputs = context.checks.find(check => check.id === 'document:ird-inputs');
  if (inputs) claims.push({text: inputs.detail, status: inputs.status, evidence: helperCheckEvidence(context, inputs)});
  claims.push({
    text: 'IRD compares interest under the lender chosen rates for the remaining term. The comparison rate, original discount treatment, day-count rules, and other fees depend on the contract. Request a written payout quote; a renewal offered rate is not automatically the IRD comparison rate.',
    status: 'definition', evidence: [],
  });
  return claims;
}

function timelineClaims(context, scopes) {
  return context.checks.filter(check => scopes.includes(check.scope) && ['term-calendar', 'maturity-distance'].some(key => check.id.endsWith(':' + key)))
    .map(check => ({
      text: check.output.expected_maturity ? `${check.detail} Calculated term end: ${check.output.expected_maturity}. Difference: ${check.output.difference_days} days.`
        : typeof check.output.days_remaining === 'number' ? `${check.output.days_remaining} calendar days from ${context.asOf} until the stated maturity.` : check.detail,
      status: check.status, evidence: helperCheckEvidence(context, check),
    }));
}

function paymentClaims(context, scopes) {
  const claims = claimsForFields(context, ['payment_amount', 'frequency'], scopes);
  if (context.scenarios[0]?.payment !== null && context.scenarios[0]?.payment !== undefined) {
    claims.push({text: `The existing analysis shows a regular principal-and-interest payment of ${money(context.scenarios[0].payment)} under the workspace assumptions. This is a modelled result, not a lender quote.`, status: 'calculation', evidence: []});
  }
  for (const check of context.checks.filter(item => ['document:tax_in_payment', 'document:insurance_in_payment'].includes(item.id))) {
    claims.push({text: check.detail, status: 'review', evidence: helperCheckEvidence(context, check)});
  }
  return claims;
}

function comparisonClaims(context) {
  if (context.scenarios.length < 2) return [{text: 'No completed offer comparison is available. I can explain the document, but I cannot invent savings or current lender rates.', status: 'missing', evidence: []}];
  return context.scenarios.slice(1, 5).map(scenario => ({
    text: `${scenario.name || 'Alternative offer'}: ${scenario.rate === null ? 'rate unavailable' : `${scenario.rate}%`}; ${scenario.interest === null ? 'interest result unavailable' : `${money(scenario.interest)} modelled interest`}; ${scenario.benefit === null ? 'economic benefit unavailable' : `${money(scenario.benefit)} modelled net benefit versus renewal`}. Offer status: ${scenario.type}. ${context.horizonMonths ? `Comparison horizon: ${context.horizonMonths} months.` : ''}`,
    status: 'calculation', evidence: [],
  }));
}

function reviewClaims(context) {
  const pending = context.checks.filter(check => ['conflict', 'review', 'incomplete'].includes(check.status));
  if (!pending.length) {
    return [{text: context.hasDocument ? 'No review checks are present in this context. That is not a certification of the document.' : 'No document has been read in this workspace. Available numbers are editable workspace inputs.', status: 'missing', evidence: []}];
  }
  return pending.slice(0, 8).map(check => ({text: `${check.title}: ${check.detail}`, status: check.status, evidence: helperCheckEvidence(context, check), checkId: check.id}));
}

function marketClaims(context) {
  if (!context.market.observations.length) return [{text: 'Official market rates are unavailable in this workspace. Reconnect and refresh the rate tracker; no rates have been substituted.', status: 'missing', evidence: []}];
  const status = context.market.status === 'live-observation' ? 'Official observation retrieved' : 'Cached observation; current rate not verified';
  return context.market.observations.map(item => ({
    text: `${item.label || item.key}: ${item.value}%. ${status}. Published ${item.observedAt}; checked ${context.market.checkedAt}. This is public benchmark data, not a personalized lender offer.`,
    status: context.market.status === 'live-observation' ? 'observation' : 'cached',
    evidence: [{id: 'market:' + item.key, source: 'official-market', page: null, line: null, excerpt: item.sourceUrl, observedAt: item.observedAt}],
  }));
}

function answerIntent(intent, context, question) {
  const scopes = requestedHelperScopes(question, intent === 'contract_rate' || intent === 'posted_rate' || intent === 'discount' || intent === 'mortgage_date' || intent === 'current_rate'
    ? ['original', 'unspecified'] : ['renewal', 'original', 'unspecified']);
  const fields = {
    contract_rate: ['contract_rate'], posted_rate: ['posted_rate'], current_rate: ['current_rate'],
    renewal_rate: ['offered_rate'], balance: ['balance'], mortgage_date: ['mortgage_start_date'],
    renewal_date: ['renewal_date', 'term_start_date'], expiry: ['offer_expiry_date'],
    maturity: ['maturity_date'], term: ['term_months'], amortization: ['amortization_months'],
  };
  let claims;
  if (intent === 'discount') claims = discountClaims(context, scopes);
  else if (intent === 'ird') claims = irdClaims(context);
  else if (intent === 'payment') claims = paymentClaims(context, scopes);
  else if (intent === 'comparison') claims = comparisonClaims(context);
  else if (intent === 'review') claims = reviewClaims(context);
  else if (intent === 'market') claims = marketClaims(context);
  else if (fields[intent]) claims = claimsForFields(context, fields[intent], scopes);
  else claims = [{text: 'Ask about contract rate, posted rate, discount, IRD, mortgage dates, term, amortization, payments, or the document review checks.', status: 'definition', evidence: []}];
  if (['maturity', 'term'].includes(intent)) claims.push(...timelineClaims(context, scopes));
  if (intent === 'renewal_rate') {
    const change = context.checks.find(check => check.id === 'document:renewal-rate-change');
    if (typeof change?.output.change_percentage_points === 'number') {
      claims.push({text: `The recorded rate change is ${change.output.change_percentage_points} percentage points (${change.output.change_basis_points} basis points). This compares different terms; it is not an IRD estimate.`, status: 'calculation', evidence: helperCheckEvidence(context, change)});
    }
  }
  if (definitions[intent]) claims.push({text: definitions[intent], status: 'definition', evidence: []});
  return claims;
}

export function answerLocalMortgageQuestion(question, workspace = {}, options = {}) {
  const normalized = normalizeHelperQuestion(question);
  if (!normalized) throw new TypeError('Enter a mortgage question');
  const context = safeHelperContext(workspace);
  let prediction = classifyHelperQuestion(question);
  if (/^(?:and )?(?:what about (?:the )?(?:renewal|original|payout)|why|explain more)$/.test(normalized)
      && helperTopics.some(topic => topic.id === options.previousIntent)) {
    prediction = {...prediction, intent: options.previousIntent, reason: 'followup'};
  }
  const claims = prediction.intent ? answerIntent(prediction.intent, context, normalized)
    : [{text: prediction.reason === 'unknown' ? 'I can answer mortgage document questions. Ask about a rate, date, term, payment, discount, or IRD.' : 'I need a more specific mortgage question. Which of these details would you like to check?', status: 'clarify', evidence: []}];
  const evidence = [...new Map(claims.flatMap(claim => claim.evidence).map(item => [item.id, item])).values()];
  return {
    id: 'answer-' + helperFingerprint({question: normalized, context: context.fingerprint, intent: prediction.intent}),
    question: question.trim(), intent: prediction.intent, claims, evidence,
    suggestions: prediction.intent ? [] : prediction.suggestions,
    model: helperModelVersion, classificationReason: prediction.reason,
    contextFingerprint: context.fingerprint,
    local: true, networkRequired: false,
  };
}
