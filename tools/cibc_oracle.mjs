// Runs CIBC's own published prepayment-charge code (mortgageprepayment.min.js, unmodified) as a test oracle.
// Usage: TZ=UTC node tools/cibc_oracle.mjs < cases.json > results.json
// Each case: {balance, payment, contract, discount, today: "YYYY-MM-DD", maturity: "YYYY-MM-DD",
//             rates: {"6":r, "12":r, "24":r, "36":r, "48":r, "60":r, "84":r, "120":r}}  (percentages, as CIBC's UI)
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "cibc_oracle", "mortgageprepayment.min.js"), "utf8");

// jQuery stand-in: every DOM call is a no-op that chains; $.extend is Object.assign. The calculation never reads the DOM.
const chain = new Proxy(function () {}, {
  get: (t, k) => (k === "val" ? () => "fixed" : k === "length" ? 0 : () => chain),
  apply: () => chain,
});
const $ = new Proxy(function () { return chain; }, {
  get: (t, k) => (k === "extend" ? (a, ...b) => Object.assign(a, ...b) : () => chain),
});
const window = { services: { calculators: { mortgagePrepayment: {}, SharedFormMethods: { toFixed: (v, n) => Number(v).toFixed(n) } } } };
const ctx = vm.createContext({ window, jQuery: $, $, document: chain, navigator: { userAgent: "node" }, console, Math, Date, setTimeout });
vm.runInContext(src, ctx);
const calc = window.services.calculators.MortgagePrepaymentCalc;
if (!calc || !calc.calculate) throw new Error("CIBC calculator object not exported");

const KEYS = { 6: "convertible6Months", 12: "closed1Year", 24: "closed2Years", 36: "closed3Years", 48: "closed4Years",
               60: "closed5Years", 84: "closed7Years", 120: "closed10Years" };
const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const posted = { prime: { rate: 0, name: "prime" } };
  for (const [t, k] of Object.entries(KEYS)) posted[k] = { rate: c.rates[t], name: k };
  window.services.calculators.mortgagePrepayment.postedRates = posted;
  window.services.calculators.mortgagePrepayment.initialModel.mortgageType = "fixed";
  calc.setPrepaymentType("full");
  calc.setMortgageType("fixed");
  calc.setMortgageBalance(c.balance);
  calc.setPaymentFrequency(12);
  calc.setPayment(c.payment);
  calc.setCurrentInterestRate(c.contract);
  calc.setInterestRateDiscount(c.discount);
  calc.setComparisonRate(0);
  calc.setCashbackAmount(0);
  const [y, m, d] = c.today.split("-").map(Number);
  calc.setCurrentDate(new Date(y, m - 1, d));
  calc.setMaturityDate(c.maturity);
  calc.calculate();
  out.push({ charge: Math.round(100 * calc.getPrepaymentChargeOnly()) / 100, type: calc.getCalculationType(),
             three: calc.get3MothsInterest(), ird: calc.getIRD(), maturity_interest: calc.getInterest2Maturity(),
             days: calc.getRemainingDays(), posted: calc.getComparisonInterestRate() });
}
process.stdout.write(JSON.stringify(out));
