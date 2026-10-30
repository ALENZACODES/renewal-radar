import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {trajectoryData, costData, rateData} from '../frontend/js/chart-data.js';
import {trajectoryOption, costOption, rateOption} from '../frontend/js/chart-options.js';
import {trajectoryView, costView, publicRateView} from '../frontend/js/chart-view.js';
import {mountMortgageCharts} from '../frontend/js/chart-runtime.js';

function analysis() {
  return {horizon_months: 36, scenarios: [
    {offer: {name: 'Renewal'}, loan: {starting_balance: 500000, total_interest: 10000},
      schedule: [{month: 1, balance: 498000, interest: 1200}, {month: 2, balance: 496000, interest: 1190}], fees_net: 0, net_cost: 10000},
    {offer: {name: 'Alternative'}, loan: {starting_balance: 500000, total_interest: 9000},
      schedule: [{month: 1, balance: 497500, interest: 1100}, {month: 2, balance: 495000, interest: 1090}], fees_net: 500, net_cost: 9500},
  ]};
}
function market() {
  return {data_status: 'live-observation', series: {
    policy_rate: {value: 2.25, code: 'V39079', observed_at: '2026-10-13', source_url: 'https://www.bankofcanada.ca/valet/'},
    prime: {value: 4.45, code: 'V80691311', observed_at: '2026-10-07', source_url: 'https://www.bankofcanada.ca/valet/'},
  }};
}

test('balance trajectories originate at actual starting debt without projecting beyond the data', () => {
  const rows = trajectoryData(analysis());
  assert.deepEqual(rows[0].points, [[0, 500000], [1, 498000], [2, 496000]]);
  assert.equal(rows[1].points.at(-1)[0], 2);
});
test('cumulative interest derives only from payment ledger interest', () => {
  assert.deepEqual(trajectoryData(analysis(), 'interest')[0].points, [[0, 0], [1, 1200], [2, 2390]]);
});
test('duplicate or unordered months and malformed financial values are rejected', () => {
  const input = analysis();
  input.scenarios[0].schedule.push({month: 1, balance: 10, interest: 10}, {month: 3, balance: NaN, interest: 10});
  assert.equal(trajectoryData(input)[0].points.length, 3);
  input.scenarios[1].loan.starting_balance = null;
  assert.equal(trajectoryData(input).length, 1);
});
test('shorter-term curves are named explicitly and excluded from the common-horizon cost chart', () => {
  const input = analysis();
  input.scenarios[1].not_comparable_full_horizon = true;
  assert.match(trajectoryData(input)[1].name, /shorter term/);
  assert.equal(costData(input).length, 1);
});
test('cost chart reconciles interest plus net fees rather than adding payment savings', () => {
  assert.deepEqual(costData(analysis())[1], {name: 'Alternative', interest: 9000, fees: 500, net: 9500});
  const input = analysis();
  input.scenarios[1].net_cost = 6000;
  assert.equal(costData(input).length, 1);
});
test('fee credits stay negative and are not silently clamped away', () => {
  const input = analysis();
  input.scenarios[1].fees_net = -500;
  input.scenarios[1].net_cost = 8500;
  assert.equal(costData(input)[1].fees, -500);
  assert.equal(costOption(input).series[1].data[1], -500);
});
test('rate chart admits only finite dated observations from the official source', () => {
  assert.equal(rateData(market()).length, 2);
  const input = market();
  input.series.prime.source_url = 'https://www.bankofcanada.ca.attacker.invalid/';
  input.series.policy_rate.observed_at = '2026-02-30';
  assert.equal(rateData(input).length, 0);
});
for (const value of [null, undefined, '4.45', NaN, Infinity, -1, 31]) {
  test(`invalid rate ${String(value)} is not displayed`, () => {
    const input = market(); input.series.prime.value = value;
    assert.equal(rateData(input).length, 1);
  });
}
test('empty or incomplete inputs do not produce invented chart values', () => {
  assert.equal(trajectoryOption(null), null);
  assert.equal(costOption(null), null);
  assert.equal(rateOption(null), null);
  assert.match(trajectoryView(null), /No completed calculation/);
  assert.equal(costView(null), '');
  assert.equal(publicRateView(null), '');
});
test('view escapes untrusted lender names and exposes data without relying on colour', () => {
  const input = analysis(); input.scenarios[0].offer.name = '<img src=x onerror=alert(1)>';
  const html = trajectoryView(input);
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;img/);
  assert.match(html, /<summary>Chart data/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /title="Download chart"/);
});
test('cached observations remain labelled cached in the chart caption', () => {
  const input = market(); input.data_status = 'cached-stale';
  assert.match(publicRateView(input), /Cached observations, not live/);
  assert.match(publicRateView(input), /2026-10-07/);
});
test('options use rich-text tooltips, distinct series colours and reduced-motion support', () => {
  const option = trajectoryOption(analysis(), 'balance', {reducedMotion: true});
  assert.equal(option.animation, false);
  assert.equal(option.tooltip.renderMode, 'richText');
  assert.equal(new Set(option.color).size, 5);
  assert.equal(option.aria.enabled, true);
  assert.equal(option.series[0].smooth, false);
});
test('dark chart labels and background change together', () => {
  const option = costOption(analysis(), {dark: true});
  assert.equal(option.textStyle.color, '#ededed');
  assert.equal(option.backgroundColor, '#242424');
});

const vendor = readFileSync(new URL('../frontend/assets/vendor/echarts-6.1.0.min.js', import.meta.url), 'utf8');
const sandbox = {setTimeout, clearTimeout, console};
runInNewContext(vendor, sandbox);
test('bundled Apache ECharts version is pinned to 6.1.0', () => {
  assert.equal(sandbox.echarts.version, '6.1.0');
});
for (const [name, option] of [
  ['debt trajectory', trajectoryOption(analysis(), 'balance', {reducedMotion: true})],
  ['interest trajectory', trajectoryOption(analysis(), 'interest', {reducedMotion: true})],
  ['cost breakdown', costOption(analysis(), {reducedMotion: true})],
  ['public rates', rateOption(market(), {reducedMotion: true})],
]) {
  test(`bundled chart engine renders nonblank ${name} SVG without a browser or network`, () => {
    const chart = sandbox.echarts.init(null, null, {renderer: 'svg', ssr: true, width: 600, height: 330});
    try {
      chart.setOption(option);
      const svg = chart.renderToSVGString();
      assert.match(svg, /<svg/);
      assert.ok(svg.length > 3000);
      assert.match(svg, /<path/);
      assert.match(svg, /<text/);
      assert.ok(!svg.includes('NaN'));
    } finally { chart.dispose(); }
  });
}

function runtimeFixture() {
  const listeners = new Map();
  const calls = {created: [], disposed: 0, resized: 0, downloads: []};
  const element = {dataset: {chart: 'trajectory', chartId: 'debt'}};
  const buttons = ['balance', 'interest'].map(mode => ({dataset: {chartMode: mode, chartTarget: 'debt'},
    setAttribute(key, value) {this[key] = value;}}));
  const root = {querySelectorAll: selector => selector === '[data-chart]' ? [element] : buttons,
    contains: () => true, addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key)};
  const library = {init: () => {
    const chart = {options: [], setOption: value => chart.options.push(value), dispose: () => calls.disposed++,
      resize: () => calls.resized++, getDataURL: () => 'data:image/svg+xml,test'};
    calls.created.push(chart); return chart;
  }};
  class Observer {constructor(callback) {this.callback = callback;} observe() {this.callback();} disconnect() {}}
  const runtime = mountMortgageCharts(root, () => ({analysis: analysis()}), {library, Observer, reducedMotion: () => true,
    download: (url, filename) => calls.downloads.push({url, filename})});
  const click = button => listeners.get('click')({target: {closest: selector => {
    if (selector === '[data-chart-mode]') return button.dataset.chartMode ? button : null;
    return button.dataset.chartDownload ? button : null;
  }}});
  return {runtime, calls, buttons, click, listeners};
}
test('chart runtime disposes old charts and resize listeners across page renders', () => {
  const env = runtimeFixture(); env.runtime.refresh(); env.runtime.refresh();
  assert.equal(env.calls.created.length, 2);
  assert.equal(env.calls.disposed, 1);
  assert.equal(env.calls.resized, 2);
  env.runtime.dispose();
  assert.equal(env.calls.disposed, 2);
  assert.equal(env.listeners.size, 0);
});
test('keyboard-compatible mode buttons switch and preserve the chosen measure', () => {
  const env = runtimeFixture(); env.runtime.refresh(); env.click(env.buttons[1]);
  assert.equal(env.buttons[1]['aria-pressed'], 'true');
  assert.equal(env.buttons[0]['aria-pressed'], 'false');
  assert.equal(env.calls.created[0].options.at(-1).series[0].data[0][1], 0);
  env.runtime.refresh();
  assert.equal(env.calls.created[1].options[0].series[0].data[0][1], 0);
});
test('chart download exports the rendered graphic without external requests', () => {
  const env = runtimeFixture(); env.runtime.refresh(); env.click({dataset: {chartDownload: 'debt'}});
  assert.deepEqual(env.calls.downloads, [{url: 'data:image/svg+xml,test', filename: 'renewal-radar-chart.svg'}]);
});
