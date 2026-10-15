/** Only bounded mortgage evidence and displayed calculations enter the local helper. */
export const helperFieldNames = new Set([
  'contract_rate', 'posted_rate', 'comparison_rate', 'contract_discount',
  'offered_rate', 'current_rate', 'balance', 'payment_amount', 'frequency',
  'term_months', 'amortization_months', 'mortgage_start_date', 'term_start_date',
  'maturity_date', 'renewal_date', 'offer_expiry_date', 'payout_date',
]);
export const helperScopes = ['original', 'renewal', 'payout', 'unspecified'];
const factStatuses = new Set(['resolved', 'review', 'conflict', 'unreadable']);

function bounded(value, limit = 240) {
  return typeof value === 'string' ? value.slice(0, limit) : '';
}

function numeric(value, minimum = 0, maximum = 1e8) {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum ? value : null;
}

function safeFactValue(field, value) {
  if (value == null) return null;
  if (field.endsWith('_date')) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const parsed = new Date(value + 'T00:00:00Z');
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
  }
  if (field === 'frequency') return typeof value === 'string' && /^(?:accelerated-)?(?:monthly|semi-monthly|biweekly|weekly)$/.test(value) ? value : null;
  if (field.endsWith('_months')) {
    const result = numeric(value, 1, 600);
    return Number.isInteger(result) ? result : null;
  }
  if (field.includes('rate') || field === 'contract_discount') return numeric(value, 0, 30);
  return numeric(value, 0, 1e8);
}

function primitiveObject(value, limit = 20) {
  const result = {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) return result;
  for (const [key, item] of Object.entries(value).slice(0, limit)) {
    if (!/^[a-z][a-z0-9_]{0,70}$/.test(key)) continue;
    if (typeof item === 'number' && Number.isFinite(item)) result[key] = item;
    else if (typeof item === 'boolean' || item === null) result[key] = item;
    else if (typeof item === 'string') result[key] = bounded(item, 120);
  }
  return result;
}

export function helperFingerprint(value) {
  const text = JSON.stringify(value);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index++) {
    hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

export function safeHelperContext(workspace = {}) {
  if (!workspace || typeof workspace !== 'object') workspace = {};
  const audit = workspace.document?.semantic_audit || {};
  const facts = {};
  for (const [key, fact] of Object.entries(audit.facts || {}).slice(0, 128)) {
    if (!fact || !helperFieldNames.has(fact.field) || !helperScopes.includes(fact.scope)) continue;
    if (key !== `${fact.scope}.${fact.field}`) continue;
    const value = safeFactValue(fact.field, fact.value);
    facts[key] = {
      field: fact.field, scope: fact.scope, value,
      status: factStatuses.has(fact.status) && (value !== null || fact.status !== 'resolved') ? fact.status : 'unreadable',
      source: fact.source === 'reviewer' ? 'reviewer' : 'document',
      evidence: Array.isArray(fact.evidence) ? fact.evidence.slice(0, 30).filter(id => typeof id === 'string').map(id => bounded(id, 80)) : [],
    };
  }
  const ledger = {};
  for (const item of [...(Array.isArray(audit.mentions) ? audit.mentions : []), ...(Array.isArray(audit.clauses) ? audit.clauses : [])].slice(0, 800)) {
    if (!item || typeof item.id !== 'string') continue;
    const id = bounded(item.id, 80);
    ledger[id] = {
      id, excerpt: bounded(item.excerpt),
      page: Number.isInteger(item.page) && item.page > 0 && item.page <= 200 ? item.page : null,
      line: Number.isInteger(item.line) && item.line > 0 && item.line <= 1200 ? item.line : null,
      source: item.source === 'reviewer' ? 'reviewer' : 'document',
    };
  }
  const clauses = (Array.isArray(audit.clauses) ? audit.clauses : []).slice(0, 400)
    .filter(item => item && ['mentioned', 'negated', 'conditional', 'example'].includes(item.assertion))
    .map(item => ({id: bounded(item.id, 80), topic: bounded(item.topic, 60), assertion: item.assertion}));
  const checks = (Array.isArray(audit.checks) ? audit.checks : []).slice(0, 200)
    .filter(item => item && typeof item.id === 'string')
    .map(item => ({
      id: bounded(item.id, 100), status: bounded(item.status, 30),
      title: bounded(item.title, 100), detail: bounded(item.detail, 500),
      scope: bounded(item.scope, 30), inputs: primitiveObject(item.inputs),
      output: primitiveObject(item.output), formula: bounded(item.formula, 200),
      evidence: Array.isArray(item.evidence) ? item.evidence.slice(0, 30).filter(id => typeof id === 'string') : [],
    }));
  const inputs = {};
  for (const field of helperFieldNames) {
    const value = safeFactValue(field, workspace.mortgage?.[field]);
    if (value !== null) inputs[field] = value;
  }
  const scenarios = (Array.isArray(workspace.analysis?.scenarios) ? workspace.analysis.scenarios : []).slice(0, 13)
    .map(item => ({
      name: bounded(item.offer?.name, 100),
      type: ['hypothetical', 'personalized', 'published'].includes(item.offer?.type) ? item.offer.type : 'unverified',
      rate: numeric(item.offer?.rate, 0, 30),
      termMonths: numeric(item.offer?.term_months, 1, 120),
      payment: numeric(item.loan?.regular_payment),
      interest: numeric(item.loan?.total_interest),
      benefit: numeric(item.vs_renewal?.net_benefit, -1e8, 1e8),
      fees: numeric(item.offer?.fees),
    }));
  const result = {
    facts, ledger, clauses, checks, inputs, scenarios,
    asOf: bounded(audit.as_of, 10),
    documentName: bounded(audit.filename || workspace.document?.filename, 120),
    hasDocument: Boolean(workspace.document),
    horizonMonths: numeric(workspace.horizon, 1, 120),
    market: {
      status: ['live-observation', 'cached-stale'].includes(workspace.market?.data_status) ? workspace.market.data_status : 'unavailable',
      checkedAt: bounded(workspace.market?.checked_at, 40),
      observations: Object.entries(workspace.market?.series || {})
        .filter(([key, item]) => ['policy_rate','prime','posted_1y','posted_3y','posted_5y','bond_5y'].includes(key)
          && item && typeof item.value === 'number' && Number.isFinite(item.value)
          && typeof item.source_url === 'string' && item.source_url.startsWith('https://www.bankofcanada.ca/valet/'))
        .map(([key, item]) => ({key, value: item.value, label: bounded(item.label, 120), observedAt: bounded(item.observed_at, 10), sourceUrl: bounded(item.source_url, 400)})),
    },
    sources: (Array.isArray(audit.sources) ? audit.sources : []).filter(item => item?.url?.startsWith('https://www.canada.ca/en/financial-consumer-agency/'))
      .slice(0, 10).map(item => ({title: bounded(item.title, 120), url: bounded(item.url, 400)})),
  };
  result.fingerprint = helperFingerprint({facts, checks, inputs, scenarios, market: result.market});
  return result;
}

export function findHelperFact(context, field, preferredScopes = ['renewal', 'original', 'unspecified']) {
  for (const scope of preferredScopes) {
    const fact = context.facts[`${scope}.${field}`];
    if (fact) return {...fact, key: `${scope}.${field}`};
  }
  if (Object.hasOwn(context.inputs, field)) {
    return {field, value: context.inputs[field], status: 'input', scope: 'workspace', source: 'workspace', evidence: [], key: `workspace.${field}`};
  }
  return null;
}

export function helperFactEvidence(context, fact) {
  if (!fact) return [];
  if (fact.source === 'workspace') {
    return [{id: fact.key, source: 'workspace', page: null, line: null, excerpt: 'Current workspace input', field: fact.field, value: fact.value}];
  }
  return fact.evidence.map(id => context.ledger[id]).filter(Boolean)
    .map(item => ({...item, field: fact.field, value: fact.value, scope: fact.scope}));
}

export function helperCheckEvidence(context, check) {
  return (check?.evidence || []).map(id => context.ledger[id]).filter(Boolean);
}

export function requestedHelperScopes(question, defaultScopes) {
  const original = /\b(?:original|old|existing)\b/i.test(question);
  const renewal = /\b(?:renewal|new)\b/i.test(question);
  if (original && renewal) return defaultScopes;
  if (/\b(?:original|old|existing)\b/i.test(question)) return ['original'];
  if (/\b(?:renewal|new)\b/i.test(question)) return ['renewal'];
  if (/\b(?:payout|discharge)\b/i.test(question)) return ['payout'];
  return defaultScopes;
}
