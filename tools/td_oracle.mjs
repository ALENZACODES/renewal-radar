// Runs TD's own published prepayment-charge code (td-prepayment.min.js, unmodified) as a test oracle.
// Usage: node tools/td_oracle.mjs < cases.json > results.json
// Each case: {amount, contract, discount, maturity:"YYYY-MM-DD", rates:[{term, rate}]}
// TD's code computes "months remaining" from *today*, so the Python side must use today's date too.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "td_oracle", "td-prepayment.min.js"), "utf8");

const services = {};
const chain = {
  service(name, spec) { services[name] = spec; return chain; },
  controller() { return chain; }, directive() { return chain; }, filter() { return chain; },
  config() { return chain; }, run() { return chain; }, factory() { return chain; },
};
const sandbox = { angular: { module: () => chain }, console, Math, Date, Number, parseFloat, JSON };
vm.createContext(sandbox);
vm.runInContext(src, sandbox);

const spec = services.calculate;                       // ["$http", "rate", fn]
const Calc = spec[spec.length - 1];
const calc = new Calc({ get: () => Promise.resolve({ data: "" }) }, {});

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((c) => {
  const rates = c.rates.map((r) => ({ term: r.term, rate: r.rate, group: "Fixed Rate Closed Mortgage" }));
  const maturity = c.maturity.replace(/-/g, "/");          // local date, as TD's date picker supplies
  const ird = calc.getRateDifferentialAmount(c.amount, c.contract, rates, c.discount, true, maturity);
  const three = calc.getInterestAmount(c.amount, c.contract);
  const irdTotal = Math.round(100 * (ird.total || 0)) / 100;
  const remaining = calc.getRemainingMon(maturity);
  // Final charge, as TD's Calculator controller sets payment.total:
  //   5 < term && 0 < term - 5 && remaining <= 12 * (term - 5) ? three-month interest : Math.max(IRD, three-month)
  const termY = c.term_months / 12;
  const final = (5 < termY && 0 < termY - 5 && remaining <= 12 * (termY - 5)) ? three : Math.max(irdTotal, three);
  return { ird: irdTotal, three, final, remaining, compare_posted: ird.currentRate ?? null };
});
process.stdout.write(JSON.stringify(out));
