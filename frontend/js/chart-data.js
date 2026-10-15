const finite = value => typeof value === 'number' && Number.isFinite(value);
const boundedName = value => String(value || 'Unnamed scenario').slice(0, 100);
export const chartColors = ['#011f5b', '#990000', '#287271', '#74649b', '#8a6916'];
export const publicRateNames = {
  policy_rate: 'Policy target', prime: 'Bank prime', posted_1y: '1-year posted',
  posted_3y: '3-year posted', posted_5y: '5-year posted', bond_5y: '5-year bond',
};

export function trajectoryData(analysis, mode = 'balance') {
  const lines = [];
  for (const scenario of (analysis?.scenarios || []).slice(0, 12)) {
    const start = scenario.loan?.starting_balance;
    if (!finite(start) || start < 0 || !Array.isArray(scenario.schedule)) continue;
    const points = [[0, mode === 'interest' ? 0 : start]];
    let cumulative = 0;
    let previousMonth = 0;
    for (const row of scenario.schedule.slice(0, 6000)) {
      if (!finite(row.month) || row.month <= previousMonth || row.month > 120) continue;
      if (!finite(row.balance) || row.balance < 0 || !finite(row.interest) || row.interest < 0) continue;
      cumulative += row.interest;
      points.push([row.month, mode === 'interest' ? Math.round(cumulative * 100) / 100 : row.balance]);
      previousMonth = row.month;
    }
    if (points.length < 2) continue;
    const short = scenario.not_comparable_full_horizon === true;
    lines.push({name: boundedName(scenario.offer?.name) + (short ? ' (shorter term)' : ''), points, short});
  }
  return lines;
}

export function costData(analysis) {
  const result = [];
  for (const scenario of (analysis?.scenarios || []).slice(0, 12)) {
    if (scenario.not_comparable_full_horizon) continue;
    const interest = scenario.loan?.total_interest;
    const fees = scenario.fees_net;
    const net = scenario.net_cost;
    if (!finite(interest) || interest < 0 || !finite(fees) || !finite(net)) continue;
    // The backend reconciles cash flows with ending debt. Reject mismatched aggregates.
    if (Math.abs(interest + fees - net) > 0.05) continue;
    result.push({name: boundedName(scenario.offer?.name), interest, fees, net});
  }
  return result;
}

export function rateData(market) {
  const result = [];
  for (const [key, name] of Object.entries(publicRateNames)) {
    const row = market?.series?.[key];
    if (!row || !finite(row.value) || row.value < 0 || row.value > 30) continue;
    const date = String(row.observed_at || '');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    const parsed = new Date(date + 'T12:00:00Z');
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) continue;
    try {
      const source = new URL(row.source_url);
      if (source.protocol !== 'https:' || source.hostname !== 'www.bankofcanada.ca') continue;
    } catch { continue; }
    result.push({name, value: row.value, date, code: String(row.code || '').slice(0, 60)});
  }
  return result;
}
