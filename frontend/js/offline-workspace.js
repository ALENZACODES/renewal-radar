export function offlineDemoWorkspace() {
  return {
    mortgage: {
      balance: 480000, offered_rate: 5.49, current_rate: 4.19,
      amortization_months: 228, term_months: 36, maturity_date: '2027-03-01',
      frequency: 'monthly', rate_type: 'fixed', lender: 'Maple Bank (illustrative)',
      insurance_status: 'uninsured', standalone: true,
      combined_loan_plan: false, existing_lender_federally_regulated: true,
      new_lender_federally_regulated: true, amortization_increase: false,
      cash_out: 0, fees_financed: 0, remaining_old_term_months: 0,
    },
    offers: [{
      name: 'Illustrative alternative', rate: 4.49, rate_type: 'fixed',
      term_months: 36, fees: 950, fee_credit: 0, type: 'hypothetical',
      annual_prepayment: 0, monthly_extra: 0,
    }],
    notice: 'Hypothetical offline example from Maple Bank, a fictional lender. No live rates or completed calculation available.',
  };
}

export async function loadInitialWorkspace(api) {
  try {
    return {data: await api.demo(), offline: false};
  } catch {
    return {data: offlineDemoWorkspace(), offline: true};
  }
}

export async function registerOfflineShell(navigatorObject = globalThis.navigator) {
  if (!navigatorObject?.serviceWorker) return {registered: false, reason: 'unsupported'};
  try {
    const registration = await navigatorObject.serviceWorker.register('/service-worker.js', {scope: '/'});
    return {registered: true, registration};
  } catch {
    return {registered: false, reason: 'unavailable'};
  }
}

export function readLocalHelperStorage(windowObject = globalThis.window) {
  try {
    return windowObject?.localStorage || null;
  } catch {
    return null;
  }
}
