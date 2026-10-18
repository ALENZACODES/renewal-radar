// Runs Simplii Financial's own prepayment calculator modules (calculator.js + pcf_rules.js, unmodified) as an oracle.
// Each case gets a fresh copy of the modules, as a fresh page load would (the rules read the previous IRD).
// Usage: TZ=UTC node tools/simplii_oracle.mjs < cases.json
// case: {balance, payment, contract, discount, today:"YYYY-MM-DD", maturity:"YYYY-MM-DD",
//        rates:{"6":r,"12":r,"24":r,"36":r,"48":r,"60":r,"84":r,"120":r}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const dir = path.join(here, "..", "data", "ratewatch", "simplii_oracle");
const calcSrc = fs.readFileSync(path.join(dir, "calculator.js"), "utf8");
const rulesSrc = fs.readFileSync(path.join(dir, "pcf_rules.js"), "utf8");
const KEYS = { 6: "convertible6Months", 12: "convertible12Months", 24: "closed2Years", 36: "closed3Years",
               48: "closed4Years", 60: "closed5Years", 84: "closed7Years", 120: "closed10Years" };
const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const postedRates = { prime: { rate: 0 } };
  for (const [t, k] of Object.entries(KEYS)) postedRates[k] = { rate: `[${c.rates[t]}]`, name: k };
  const window = { postedRates };
  const ctx = vm.createContext({ window, postedRates, Model: { isDiscountVisible: () => true, isCurrentInterestRateVisible: () => true },
                                 Math, Date, parseFloat, console });
  ctx.Calculator = undefined;
  vm.runInContext(calcSrc, ctx);
  vm.runInContext(rulesSrc, ctx);
  const k = window.Calculator;
  ctx.Calculator = k;
  k.setPrepaymentType("full"); k.setMortgageType("fixed"); k.setMortgageBalance(c.balance);
  k.setPaymentFrequency(12); k.setPayment(c.payment); k.setCurrentInterestRate(c.contract);
  k.setInterestRateDiscount(c.discount); k.setComparisonRate(0); k.setCashbackAmount(0);
  const [y, m, d] = c.today.split("-").map(Number), [my, mm, md] = c.maturity.split("-").map(Number);
  k.setCurrentDate(new Date(y, m - 1, d)); k.setMaturityDate(new Date(my, mm - 1, md));
  k.calculate();
  out.push({ charge: Math.round(100 * k.getPrepaymentCharge()) / 100, type: k.getCalculationType(), ird: k.getIRD(),
             three: k.get3MothsInterest(), posted: k.getPostedInterestRate(), days: k.getRemainingDays() });
}
process.stdout.write(JSON.stringify(out));
