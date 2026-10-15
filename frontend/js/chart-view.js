import {esc, money} from './ui.js';
import {trajectoryData, costData, rateData} from './chart-data.js';

const download = kind => `<button type="button" class="chart-icon" data-chart-download="${kind}" title="Download chart" aria-label="Download ${kind} chart">\u21e9</button>`;
function table(headers, rows) {
  return `<details class="chart-data"><summary>Chart data</summary><div class="table-scroll"><table><thead><tr>${headers.map(x => `<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}

export function trajectoryView(analysis, id = 'trajectory') {
  const lines = trajectoryData(analysis);
  if (!lines.length) return '<div class="empty">No completed calculation available.</div>';
  const rows = lines.map(line => [line.name, money(line.points[0][1]), money(line.points.at(-1)[1]), `${line.points.at(-1)[0]} months`]);
  return `<div class="chart-toolbar"><div class="chart-segment" role="group" aria-label="Trajectory measure">
    <button type="button" data-chart-mode="balance" data-chart-target="${esc(id)}" aria-pressed="true">Balance</button>
    <button type="button" data-chart-mode="interest" data-chart-target="${esc(id)}" aria-pressed="false">Interest</button>
    </div>${download(id)}</div><div class="interactive-chart" data-chart="trajectory" data-chart-id="${esc(id)}" aria-label="Mortgage trajectory"></div>
    ${table(['Scenario', 'Starting debt', 'Ending debt', 'Modelled term'], rows)}`;
}

export function costView(analysis) {
  const rows = costData(analysis);
  if (!rows.length) return '';
  return `<section class="chart-band"><div class="card-head"><div><h3>Where borrowing costs go</h3><p>Interest and net fees over ${esc(analysis.horizon_months)} months. Shorter terms excluded.</p></div>${download('cost')}</div>
    <div class="interactive-chart chart-cost" data-chart="cost" data-chart-id="cost" aria-label="Comparable borrowing costs"></div>
    ${table(['Scenario', 'Interest', 'Net fees / credits', 'Total cost'], rows.map(row => [row.name, money(row.interest), money(row.fees), money(row.net)]))}</section>`;
}

export function publicRateView(market) {
  const rows = rateData(market);
  if (!rows.length) return '';
  const status = market.data_status === 'live-observation' ? 'Latest official observations' : 'Cached observations, not live';
  return `<section class="chart-band"><div class="card-head"><div><h3>Public rate landscape</h3><p>${esc(status)}. Different benchmarks, not borrower quotes.</p></div>${download('rates')}</div>
    <div class="interactive-chart chart-rates" data-chart="rates" data-chart-id="rates" aria-label="Dated public rate benchmarks"></div>
    ${table(['Benchmark', 'Rate', 'Observation date', 'Official series'], rows.map(row => [row.name, row.value.toFixed(2) + '%', row.date, row.code]))}</section>`;
}
