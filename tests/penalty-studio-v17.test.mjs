import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {decimalNumber, timelineRequest, penaltyCurveOption, penaltyStudioView, exitCostExample} from '../frontend/js/penalty-studio.js';
import {state, resetState, analyzeBody, legacyPenaltyMethod} from '../frontend/js/state.js';

function workspace() {
  return {mortgage: {balance: 200000, current_rate: 5.14, remaining_old_term_months: 2,
    amortization_months: 300, frequency: 'monthly', rate_type: 'fixed'}, penaltyTimeline: {
    modelled_maturity: '2026-03-31', regular_payment: '1179', transitions: [],
    source_url: 'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html',
    assumptions: ['Entered rates are a scenario, not a forecast.'],
    points: [0, 1, 2].map((month, i) => ({month, date: ['2026-01-31', '2026-02-28', '2026-03-31'][i],
      remaining_months: 2 - month, balance: String(200000 - month * 500), bucket_months: null, comparison_rate: '3.75',
      penalty: {core_charge: month === 2 ? '0' : '2570', three_month_interest: month === 2 ? '0' : '2570',
        interest_rate_differential: month === 2 ? '0' : '1000', total_estimate: month === 2 ? '350' : '2920',
        controlling_method: '3_months', status: month === 2 ? 'no_charge_modelled' : 'estimate', formulas: ['Known formula'], missing_fields: [], warnings: []}})),
  }};
}

test('timeline request preserves missing discount rather than assuming one', () => {
  const request = timelineRequest(workspace());
  assert.equal(request.discount, null);
  assert.equal(request.method, 'simple_differential');
  assert.equal(request.balance, '200000');
  assert.equal(request.frequency, 'monthly');
});
test('illustrative exit-cost examples are detached and labelled as fictional', () => {
  const sample = exitCostExample(); sample.ladder[0].rate = '1';
  assert.equal(exitCostExample().ladder[0].rate, '6.09');
  const input = workspace(); input.penaltyInputs = exitCostExample(); input.penaltyExample = true;
  assert.match(penaltyStudioView(input), /Fictional exit-cost example/);
});
test('legacy methods map to detailed equivalents without inventing unknown methodologies', () => {
  const input = workspace(); input.penaltyInputs = {contract_method: 'posted-discount'};
  assert.equal(timelineRequest(input).method, 'posted_minus_discount');
  input.penaltyInputs.contract_method = 'unknown';
  assert.equal(timelineRequest(input).method, 'undocumented');
});
test('empty or incomplete ladders never fall back to the unrelated single rate', () => {
  const input = workspace(); input.penaltyInputs = {use_ladder: true, comparison_rate: '3.75', ladder: [{months: 12, rate: ''}]};
  const request = timelineRequest(input);
  assert.equal(request.comparison_rate, null);
  assert.deepEqual(request.ladder, []);
  input.penaltyInputs.ladder[0].rate = '0';
  assert.deepEqual(timelineRequest(input).ladder, [{months: 12, rate: '0'}]);
});
test('zero comparison rates and discounts are explicit valid values', () => {
  const input = workspace(); input.penaltyInputs = {original_discount: 0, comparison_rate: 0};
  assert.equal(timelineRequest(input).discount, '0');
  assert.equal(timelineRequest(input).comparison_rate, '0');
});
for (const value of [null, undefined, '', ' ', NaN, Infinity, true, false, [], {}]) {
  test(`invalid monetary datum ${String(value)} stays unknown on the curve`, () => assert.equal(decimalNumber(value), null));
}
test('curve values remain un-smoothed monthly steps and null gaps are not connected', () => {
  const input = workspace(); input.penaltyTimeline.points[0].penalty.core_charge = null;
  const option = penaltyCurveOption(input.penaltyTimeline);
  assert.equal(option.series[0].data[0], null);
  assert.equal(option.series[0].connectNulls, false);
  assert.equal(option.series[0].step, 'end');
  assert.equal(option.series[0].smooth, false);
  assert.equal(option.yAxis.min, 0);
  assert.equal(option.tooltip.renderMode, 'richText');
});
test('selected scenario is marked and selection is safely clamped', () => {
  const option = penaltyCurveOption(workspace().penaltyTimeline, {}, 999);
  assert.equal(option.series[0].markLine.data[0].xAxis, '2026-03-31');
});
test('unknown final charge is not shown as zero or the three-month floor', () => {
  const input = workspace(); input.penaltyTimeline.points[0].penalty.core_charge = null;
  input.penaltyTimeline.points[0].penalty.total_estimate = null;
  input.penaltyTimeline.points[0].penalty.status = 'floor_only';
  const html = penaltyStudioView(input);
  assert.match(html, /FINAL CHARGE UNKNOWN/);
  assert.match(html, /Final charge needs contract evidence/);
  assert.match(html, /Core penalty<\/span><strong>Unknown/);
});
test('view separates fees, method assumptions, transitions and dated tabular values', () => {
  const input = workspace();
  input.penaltyTimeline.transitions = [{date: '2026-02-28', remaining_months: 1, to_bucket_months: 6, comparison_rate: '3.75'}];
  const html = penaltyStudioView(input);
  assert.match(html, /Fees remain separate from the graph/);
  assert.match(html, /Rate-bucket transitions/);
  assert.match(html, /Full dated timeline/);
  assert.match(html, /Months ahead for payout scenario/);
  assert.match(html, /not a rate forecast/);
});
test('untrusted evidence and error messages cannot inject markup', () => {
  const input = workspace(); input.penaltyTimeline.assumptions.push('<img onerror=alert(1)>');
  input.penaltyTimelineError = '<script>bad()</script>';
  const html = penaltyStudioView(input);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;script&gt;/);
});
test('resetting the demo clears timeline, selected month and contract inputs', () => {
  state.penaltyTimeline = workspace().penaltyTimeline; state.penaltyInputs = {fees: 900}; state.penaltyMonth = 2;
  resetState({mortgage: workspace().mortgage, offers: []});
  assert.equal(state.penaltyTimeline, null);
  assert.equal(state.penaltyInputs, null);
  assert.equal(state.penaltyMonth, 0);
});
test('new contract methods and empty fields remain compatible with existing reports', () => {
  resetState({mortgage: workspace().mortgage, offers: []});
  state.penaltyInputs = {remaining_term_months: 2, contract_method: 'present_value', original_discount: '', comparison_rate: ''};
  assert.equal(analyzeBody().penalty.contract_method, 'unknown');
  assert.equal(analyzeBody().penalty.original_discount, null);
  assert.equal(analyzeBody().penalty.comparison_rate, null);
  assert.equal(legacyPenaltyMethod('simple_differential'), 'simple');
  assert.equal(legacyPenaltyMethod('posted_minus_discount'), 'posted-discount');
});
test('bundled ECharts renders the penalty graph nonblank with no server connection', () => {
  const sandbox = {console, setTimeout, clearTimeout};
  runInNewContext(readFileSync(new URL('../frontend/assets/vendor/echarts-6.1.0.min.js', import.meta.url), 'utf8'), sandbox);
  const chart = sandbox.echarts.init(null, null, {renderer: 'svg', ssr: true, width: 390, height: 330});
  try {
    chart.setOption(penaltyCurveOption(workspace().penaltyTimeline, {reducedMotion: true}));
    const svg = chart.renderToSVGString();
    assert.ok(svg.length > 3000);
    assert.match(svg, /<path/);
    assert.ok(!svg.includes('NaN'));
  } finally {chart.dispose();}
});
