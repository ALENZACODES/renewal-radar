// Runs Community Trust's own prepayment penalty calculator logic
// (class MortgagePrePaymentPenaltyCalculatorPage in the lender's theme code,
// data/ratewatch/community_trust_oracle/pages.js, fetched by
// tools/fetch_community_trust_oracle.py).
//
// The class's three computations are transcribed line for line below —
// monthDiff, the remaining-term band that selects the posted rate, calculate_ird
// and calculate_3mi — and the posted rates (window.rate_1..rate_5) and the
// business variant (window.business) are read from the lender's own calculator
// page as fetched, so a refetch re-points the oracle at the current build.
// The calculator's $300 full-repayment addition is a discharge fee, not part of
// the prepayment charge; it is returned separately and never added here.
//
// Usage: node tools/community_trust_oracle.mjs < cases.json
// case: {balance, contract, months}   (fixed rate, full prepayment)
// answer: {charge, ird, three_month, posted_rate, comparison_rate, discharge_fee}
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const dir = path.join(here, "..", "data", "ratewatch", "community_trust_oracle");
const page = fs.readFileSync(path.join(dir, "page.html"), "utf8");

const rate = (n) => {
  const m = page.match(new RegExp(`rate_${n}\\s*=\\s*([0-9.]+)`));
  if (!m) throw new Error(`window.rate_${n} not found on the fetched calculator page`);
  return Number(m[1]);
};
const business = (page.match(/window\.business\s*=\s*"([^"]+)"/) || [])[1] || "ctc";
const RATES = { 1: rate(1), 2: rate(2), 3: rate(3), 4: rate(4), 5: rate(5) };

// --- transcribed from MortgagePrePaymentPenaltyCalculatorPage -------------------
function monthDiff(date1, date2) {
  let months;
  months = (date2.getFullYear() - date1.getFullYear()) * 12;
  months -= date1.getMonth();
  months += date2.getMonth();
  return months <= 0 ? 0 : months;
}

function postedFor(diff) {
  if (diff >= 54 && diff <= 78) return RATES[5];
  else if (diff >= 42 && diff <= 53) return RATES[4];
  else if (diff >= 30 && diff <= 41) return RATES[3];
  else if (diff >= 18 && diff <= 29) return RATES[2];
  else return RATES[1];
}

function calculate_ird(data) {
  let d = data.pre_payment_amount;
  let a = data.current_interest_rate / 100;
  let e = data.remaining_term;
  let b = (data.current_posted_rate - 1) / 100;
  if (business == 'questbank') {
    b = (data.current_posted_rate) / 100;
  }
  let c = a - b;
  let f = (c * d * e) / 12;
  return f;
}

function calculate_3mi(data) {
  let a = data.pre_payment_amount;
  let b = data.current_interest_rate / 100;
  let c = a * b;
  let d = c / 4;
  return d;
}
// --- end of transcription --------------------------------------------------------

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const answers = cases.map((c) => {
  // the page derives the remaining term from the maturity date's year/month only
  const data = {
    pre_payment_amount: c.balance,
    current_interest_rate: c.contract,
    remaining_term: c.months,
    current_posted_rate: postedFor(c.months),
  };
  const ird = calculate_ird(data);
  const three = calculate_3mi(data);
  const charge = three > ird ? three : ird;   // fixed rate: the greater of the two
  return {
    charge: Math.round(charge * 100) / 100,
    ird: Math.round(ird * 100) / 100,
    three_month: Math.round(three * 100) / 100,
    posted_rate: data.current_posted_rate,
    comparison_rate: business === "questbank" ? data.current_posted_rate : data.current_posted_rate - 1,
    discharge_fee: 300,
    rates_table: RATES,
  };
});
process.stdout.write(JSON.stringify(answers));
