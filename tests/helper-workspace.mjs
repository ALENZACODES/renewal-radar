export function helperWorkspace() {
  const values = {
    'original.contract_rate': 4.39, 'original.posted_rate': 5.69,
    'original.contract_discount': 1.3, 'original.current_rate': 4.39,
    'original.mortgage_start_date': '2022-03-01',
    'original.maturity_date': '2027-03-01', 'original.term_months': 60,
    'renewal.offered_rate': 5.49, 'renewal.balance': 480000,
    'renewal.term_months': 36, 'renewal.amortization_months': 240,
    'renewal.maturity_date': '2030-03-01', 'renewal.term_start_date': '2027-03-01',
    'renewal.renewal_date': '2027-03-01', 'renewal.offer_expiry_date': '2027-02-15',
    'renewal.payment_amount': 3100, 'renewal.frequency': 'monthly',
  };
  const facts = {};
  const mentions = [];
  for (const [key, value] of Object.entries(values)) {
    const [scope, field] = key.split('.');
    const id = 'mention-' + key;
    facts[key] = {scope, field, value, status: 'resolved', source: 'ocr', evidence: [id]};
    mentions.push({id, page: scope === 'original' ? 1 : 2, line: mentions.length + 1, excerpt: `${scope} ${field}: ${value}`});
  }
  return {
    mortgage: {balance: 480000, offered_rate: 5.49, current_rate: 4.39,
      amortization_months: 240, term_months: 36, maturity_date: '2030-03-01', frequency: 'monthly'},
    horizon: 36,
    document: {filename: 'mortgage.pdf', semantic_audit: {
      filename: 'mortgage.pdf', as_of: '2026-10-14', facts, mentions,
      clauses: [{id: 'clause-ird', topic: 'ird', assertion: 'conditional', page: 2, line: 19, excerpt: 'Interest rate differential applies if discharged early.'}],
      checks: [
        {id: 'original:rate-discount', scope: 'original', status: 'consistent', title: 'Rate discount', detail: 'The discount matches.', inputs: {posted_rate: 5.69, contract_rate: 4.39, contract_discount: 1.3}, output: {calculated_discount_points: 1.3}, evidence: ['mention-original.contract_rate', 'mention-original.posted_rate']},
        {id: 'renewal:term-calendar', scope: 'renewal', status: 'consistent', title: 'Term dates', detail: 'The maturity matches.', inputs: {term_months: 36}, output: {expected_maturity: '2030-03-01', difference_days: 0}, evidence: ['mention-renewal.term_months']},
        {id: 'document:ird-inputs', scope: 'document', status: 'incomplete', title: 'IRD inputs', detail: 'A renewal rate is not automatically an IRD comparison rate.', output: {missing_fields: ['payout.comparison_rate']}, evidence: ['clause-ird']},
      ],
      sources: [{title: 'FCAC penalties', url: 'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html'}],
    }},
    analysis: {scenarios: [
      {offer: {name: 'Renewal', type: 'hypothetical', rate: 5.49, term_months: 36, fees: 0}, loan: {regular_payment: 3278.31, total_interest: 76000}, vs_renewal: {net_benefit: 0}},
      {offer: {name: 'Alternative', type: 'hypothetical', rate: 4.49, term_months: 36, fees: 950}, loan: {regular_payment: 3100, total_interest: 63000}, vs_renewal: {net_benefit: 12050}},
    ]},
  };
}

export function memoryStorage() {
  const values = new Map();
  const writes = [];
  return {
    values, writes,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => {values.set(key, value); writes.push({key, value});},
    removeItem: key => values.delete(key),
  };
}
