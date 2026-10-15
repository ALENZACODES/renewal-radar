// Runs National Bank's own prepayment-charges calculator script (fixed rate, full payout) as a test oracle.
// The script is cut verbatim from NBC's form by tools/fetch_nbc_oracle.py; form fields are plain {value} objects.
// Usage: node tools/nbc_oracle.mjs < cases.json   case: {balance, contract, posted, months}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const script = new vm.Script(fs.readFileSync(path.join(here, "..", "data", "ratewatch", "nbc_oracle", "fixed_total.js"), "utf8"));
const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const f = () => ({ value: null });
  const ctx = vm.createContext({
    console: { log() {} }, loanAmountTotalFixed: { value: c.balance }, fixedInterestRate: { value: c.contract },
    standardRateFixed: { value: c.posted }, termMonthsBoxFixed: { value: c.months },
    monthInterest: f(), calculIndemnite: f(), indemniteSimplifie: f(), resultBox: f(), montantFraisText: f(),
  });
  script.runInContext(ctx);
  out.push({ charge: Math.round(100 * ctx.resultBox.value) / 100, ird: ctx.calculIndemnite.value, three: ctx.indemniteSimplifie.value });
}
process.stdout.write(JSON.stringify(out));
