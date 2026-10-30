import {esc, money, percent, field, options, pageHead, button, dt} from './ui.js';

const methods = [['undocumented', 'Unknown contract method'], ['simple_differential', 'Simple rate differential'],
  ['posted_minus_discount', 'Posted rate minus discount'], ['present_value', 'Present-value approximation']];
const legacyMethods = {unknown: 'undocumented', simple: 'simple_differential', 'posted-discount': 'posted_minus_discount'};
export function exitCostExample() {
  return {balance: '200000', current_rate: '5.14', remaining_term_months: '42', amortization_months: '300',
    comparison_rate: '4.49', original_discount: '1.5', fees: '350', rate_type: 'fixed',
    contract_method: 'present_value', bucket_rule: 'ceiling', use_ladder: true,
    ladder: [{months: 6, rate: '6.09'}, {months: 12, rate: '6.09'}, {months: 24, rate: '5.39'},
      {months: 36, rate: '6.05'}, {months: 48, rate: '5.99'}, {months: 60, rate: '6.09'}]};
}
export const decimalNumber = value => !['number','string'].includes(typeof value) || String(value).trim() === '' || !Number.isFinite(Number(value)) ? null : Number(value);

export function timelineRequest(workspace) {
  const m = workspace.mortgage, p = workspace.penaltyInputs || {};
  const method = legacyMethods[p.contract_method] || p.contract_method || 'simple_differential';
  return {
    balance: String(p.balance ?? m.balance), contract_rate: String(p.current_rate ?? m.current_rate),
    remaining_months: Number(p.remaining_term_months ?? m.remaining_old_term_months),
    amortization_months: Number(p.amortization_months ?? m.amortization_months),
    start_date: p.start_date || new Date().toISOString().slice(0, 10),
    comparison_rate: p.use_ladder || p.comparison_rate === '' ? null : String(p.comparison_rate ?? 3.75),
    discount: p.original_discount === '' || p.original_discount === undefined ? null : String(p.original_discount),
    fees: String(p.fees ?? 0), rate_type: p.rate_type || m.rate_type,
    frequency: m.frequency, method, bucket_rule: p.bucket_rule || 'ceiling',
    ladder: p.use_ladder ? (p.ladder || []).filter(row => row.rate !== '').map(row => ({months: row.months, rate: String(row.rate)})) : [],
  };
}

export function penaltyCurveOption(timeline, settings = {}, selected = 0) {
  const points = timeline?.points || [];
  if (!points.length) return null;
  const ink = settings.dark ? '#ededed' : '#333333';
  const fields = [['Modelled charge', 'core_charge', '#011f5b'], ['Three-month interest', 'three_month_interest', '#3778a3'], ['IRD estimate', 'interest_rate_differential', '#990000']];
  return {
    animation: !settings.reducedMotion, animationDuration: 250,
    backgroundColor: settings.dark ? '#242424' : '#fff',
    textStyle: {fontFamily: 'Inter', color: ink, fontSize: 13},
    aria: {enabled: true, label: {description: 'Illustrative mortgage exit charge, three-month interest and interest rate differential at calendar-month anniversaries. Missing final charges remain unknown.'}},
    legend: {type: 'scroll', top: 0, textStyle: {color: ink, fontSize: 12}},
    grid: {left: 8, right: 18, top: 45, bottom: 70, containLabel: true},
    tooltip: {trigger: 'axis', renderMode: 'richText', confine: true,
      valueFormatter: value => value === null ? 'Unknown' : money(value, 2)},
    xAxis: {type: 'category', boundaryGap: false, data: points.map(point => point.date),
      axisLabel: {color: ink, hideOverlap: true, showMaxLabel: false, formatter: value => value.slice(0, 7)}},
    yAxis: {type: 'value', min: 0, axisLabel: {color: ink, formatter: value => new Intl.NumberFormat('en-CA', {notation: 'compact'}).format(value)},
      splitLine: {lineStyle: {color: settings.dark ? '#444' : '#e1e1e1'}}},
    dataZoom: [{type: 'slider', bottom: 4, height: 20, showDetail: false}, {type: 'inside', zoomOnMouseWheel: 'ctrl'}],
    series: fields.map(([name, key, color], i) => ({name, type: 'line', step: 'end', smooth: false,
      showSymbol: points.length === 1, connectNulls: false,
      data: points.map(point => decimalNumber(point.penalty[key])),
      lineStyle: {color, width: i === 0 ? 4 : 2, type: i === 1 ? 'dashed' : 'solid'}, itemStyle: {color},
      markLine: i === 0 ? {silent: true, symbol: 'none', label: {show: false}, lineStyle: {type: 'dotted', color: ink},
        data: [{xAxis: points[Math.min(Math.max(0, selected), points.length - 1)].date}]} : undefined,
    })),
  };
}

export function penaltyStudioView(workspace) {
  const m = workspace.mortgage, p = workspace.penaltyInputs || {}, timeline = workspace.penaltyTimeline;
  const request = timelineRequest(workspace), points = timeline?.points || [];
  const selected = Math.min(Math.max(0, workspace.penaltyMonth || 0), Math.max(0, points.length - 1));
  const point = points[selected], result = point?.penalty;
  const floorOnly = result?.core_charge == null;
  const ladder = p.ladder || [6, 12, 24, 36, 48, 60].map(months => ({months, rate: ''}));
  const metric = (label, value, note) => `<div class="penalty-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
  return `${pageHead('EXIT COST INTELLIGENCE', 'Mortgage exit costs', 'Contract-aware penalty scenarios, from today to the end of your term.', button('Load illustration', 'penalty-example', 'ghost') + button('Use workspace', 'penalty-workspace', 'ghost') + button('Update timeline', 'calc-penalty', 'dark'))}
    ${workspace.penaltyExample ? '<div class="notice mb"><strong>Fictional exit-cost example.</strong> Rates, discount and fees are illustrative inputs, not a verified lender quote.</div>' : ''}<details id="penalty-inputs" class="penalty-input-band" ${workspace.penaltyInputsOpen ? 'open' : ''}><summary>Contract and payout inputs</summary><div class="form-grid mt">
      ${field('Outstanding principal (CAD)', 'balance', request.balance, 'number', '', 'penalty-field')}
      ${field('Contract rate (%)', 'current_rate', request.contract_rate, 'number', '', 'penalty-field')}
      ${field('Remaining term (months)', 'remaining_term_months', request.remaining_months, 'number', '', 'penalty-field')}
      ${field('Remaining amortization (months)', 'amortization_months', request.amortization_months, 'number', '', 'penalty-field')}
      ${field('Projection start date', 'start_date', request.start_date, 'date', '', 'penalty-field')}
      ${field('Contract method', 'contract_method', options(methods, request.method), 'select', '', 'penalty-field')}
      ${field('Comparison rate (%)', 'comparison_rate', p.comparison_rate ?? 3.75, 'number', '', 'penalty-field')}
      ${field('Documented original discount (points)', 'original_discount', p.original_discount ?? '', 'number', '', 'penalty-field')}
      ${field('Separate discharge / other fees (CAD)', 'fees', request.fees, 'number', '', 'penalty-field')}
      ${field('Mortgage type', 'rate_type', options([['fixed', 'Fixed'], ['variable', 'Variable']], request.rate_type), 'select', '', 'penalty-field')}
    </div><details class="penalty-ladder"><summary>Comparison-rate term ladder</summary>
      <label class="penalty-toggle"><input type="checkbox" class="penalty-field" data-key="use_ladder" ${p.use_ladder ? 'checked' : ''}>Use entered term-specific rates</label>
      ${field('Term bucket convention', 'bucket_rule', options([['ceiling', 'At least remaining term'], ['nearest', 'Nearest term; longer at ties']], request.bucket_rule), 'select', '', 'penalty-field')}
      <div class="penalty-ladder-grid">${ladder.map((bucket, index) => `<label><span>${bucket.months} months</span><input class="penalty-ladder-rate" data-index="${index}" type="number" min="0" max="30" step="0.001" value="${esc(bucket.rate)}" aria-label="${bucket.months}-month comparison rate"></label>`).join('')}</div>
      <p class="fineprint">User-entered rate snapshot. Confirm the lender's term-selection rule and discount treatment.</p></details>
    </details>
    ${workspace.penaltyTimelineError ? `<div class="notice warn" role="status">${esc(workspace.penaltyTimelineError)}</div>` : ''}
    <section class="penalty-output-band"><div class="penalty-output-heading"><div><div class="eyebrow">${floorOnly ? 'FINAL CHARGE UNKNOWN' : 'ILLUSTRATIVE EXIT CHARGE'}</div><h2>${esc(point ? dt(point.date) : 'No timeline calculated')}</h2></div><span class="penalty-status">${esc(result?.status === 'no_charge_modelled' ? 'No charge modelled' : floorOnly ? 'Evidence required' : 'Modelled, not quoted')}</span></div>
      <div class="penalty-summary-grid">
        ${metric('Core penalty', floorOnly ? 'Unknown' : money(result.core_charge, 2), floorOnly ? 'Final charge needs contract evidence' : result?.controlling_method === 'ird' ? 'IRD controls' : result?.controlling_method === '3_months' ? 'Three-month interest controls' : 'No charge modelled')}
        ${metric('Three-month interest', result ? money(result.three_month_interest, 2) : '—', 'Not a final charge when IRD is unknown')}
        ${metric('IRD estimate', result?.interest_rate_differential == null ? 'Unknown' : money(result.interest_rate_differential, 2), request.method === 'present_value' ? 'Present-value approximation' : 'Selected contract method')}
        ${metric('Including entered fees', result?.total_estimate == null ? 'Unknown' : money(result.total_estimate, 2), 'Fees remain separate from the graph')}
      </div>
      ${points.length ? `<div class="penalty-date-control"><label for="penalty-month">Payout scenario: ${esc(dt(point.date))} &middot; ${point.remaining_months} months remain</label><input id="penalty-month" class="penalty-month" type="range" min="0" max="${points.length - 1}" step="1" value="${selected}" aria-label="Months ahead for payout scenario"><div><span>${esc(dt(points[0].date))}</span><span>${esc(dt(points.at(-1).date))}</span></div></div>
        <div class="chart-toolbar"><h3>Exit-cost timeline</h3><button type="button" class="chart-icon" data-chart-download="penalty" title="Download chart" aria-label="Download penalty chart">&#8681;</button></div><div class="interactive-chart penalty-chart" data-chart="penalty" data-chart-id="penalty" aria-label="Mortgage penalty timeline"></div>
        <div class="penalty-facts">${metric('Projected balance', money(point.balance), 'Scheduled payments only')}${metric('Applicable comparison', point.comparison_rate == null ? 'Unknown' : percent(point.comparison_rate), point.bucket_months ? `${point.bucket_months}-month bucket` : p.use_ladder ? 'No matching term' : 'Entered single rate')}${metric('Modelled maturity', dt(timeline.modelled_maturity), 'Based on entered remaining months')}</div>
        <details class="penalty-audit"><summary>Calculation evidence and assumptions</summary><ul>${[...(result.formulas || []), ...(result.missing_fields || []).map(x => 'Missing: ' + x), ...(result.warnings || []), ...timeline.assumptions].map(note => `<li>${esc(note)}</li>`).join('')}</ul><a href="${esc(timeline.source_url)}" target="_blank" rel="noopener noreferrer">FCAC prepayment guidance</a></details>
        ${timeline.transitions.length ? `<h3 class="mt2">Rate-bucket transitions</h3><div class="penalty-transitions">${timeline.transitions.map(change => `<div><strong>${esc(dt(change.date))}</strong><span>${change.remaining_months} months left</span><b>${change.to_bucket_months ? change.to_bucket_months + '-month term' : 'No matching bucket'}</b><span>${change.comparison_rate == null ? 'Unknown rate' : percent(change.comparison_rate)}</span></div>`).join('')}</div>` : ''}
        <details class="chart-data"><summary>Full dated timeline</summary><div class="table-scroll"><table><thead><tr><th>Date</th><th>Balance</th><th>Three months</th><th>IRD</th><th>Core charge</th><th>With fees</th></tr></thead><tbody>${points.map(row => `<tr><td>${esc(row.date)}</td><td>${esc(money(row.balance, 2))}</td><td>${esc(money(row.penalty.three_month_interest, 2))}</td><td>${row.penalty.interest_rate_differential == null ? 'Unknown' : esc(money(row.penalty.interest_rate_differential, 2))}</td><td>${row.penalty.core_charge == null ? 'Unknown' : esc(money(row.penalty.core_charge, 2))}</td><td>${row.penalty.total_estimate == null ? 'Unknown' : esc(money(row.penalty.total_estimate, 2))}</td></tr>`).join('')}</tbody></table></div></details>` : '<p>No completed timeline is available.</p>'}
    </section><div class="notice warn mt">Static comparison-rate scenario, not a rate forecast or a lender payout quote. A lower future penalty alone does not mean waiting or refinancing has the lowest total borrowing cost.</div>`;
}
