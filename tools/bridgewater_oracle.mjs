// Runs Bridgewater Bank's own IRD calculator component (an ES5 class in its Angular bundle bwb-module.js, cut
// verbatim) with stand-in Angular services: the bond-rate service holds the bank's published bond yields and the form
// holds the inputs. The component's own calculate() computes the charge.
// Usage: TZ=UTC node tools/bridgewater_oracle.mjs < cases.json
// case: {principal, lump_sum, balance, rate, term_id (2-6 = 1-5 yr fixed, 7/8 = 7/10 yr), start, maturity, today,
//        bonds:[r1y, r2y, r3y, r4y, r5y]}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "bridgewater_oracle", "bwb-module.js"), "utf8");
const a0 = src.indexOf("e_=function(){function t(t,e,n,r,o,i){this.formBuilder=t,this.bondRatesService=e");
const b0 = src.indexOf(",n_=Wl(", a0);
if (a0 < 0 || b0 < 0) throw new Error("Bridgewater bundle changed: IRD calculator component not found");
const classSrc = src.slice(a0 + 3, b0);                       // the IIFE that returns the component class
const t0 = src.indexOf("this.MORTAGE_TERMS=[");
const t1 = src.indexOf("]", t0);
const termsSrc = src.slice(t0 + "this.MORTAGE_TERMS=".length, t1 + 1);
const ctx = vm.createContext({ Math, Date, Number, zb: {}, qb: 20, Bb: "" });
const Component = vm.runInContext("(" + classSrc + ")", ctx);
const TERMS = vm.runInContext("(" + termsSrc + ")", ctx);

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const bondRatesService = { bondRates: { terms: c.bonds.map((rate, i) => ({ term: i + 1, rate })) } };
  const calc = new Component({}, bondRatesService, { MORTAGE_TERMS: TERMS }, {}, {}, {});
  calc.MORTAGE_TERMS = TERMS;
  const [ty, tm, td] = c.today.split("-").map(Number);
  calc.today = new Date(ty, tm - 1, td); calc.today.setHours(0, 0, 0, 0);
  const [sy, sm, sd] = c.start.split("-").map(Number), [my, mm, md] = c.maturity.split("-").map(Number);
  const value = { principalAmount: c.principal, lumpSum: c.lump_sum || 0, prepaymentAmount: c.balance,
                  balanceAmount: c.balance, rate: c.rate, term: c.term_id, startDate: new Date(sy, sm - 1, sd) };
  const endDate = new Date(my, mm - 1, md);
  calc.form = { value, get: (k) => ({ value: k === "endDate" ? endDate : value[k] }) };
  calc.calculate();
  const charge = calc.penaltyType === "ird" ? calc.irdPenalty : calc.penaltyType === "threeMonth" ? calc.threeMonthPenalty : 0;
  out.push({ charge: Math.round(100 * charge) / 100, type: calc.penaltyType || null, months: calc.monthsToMaturity() });
}
process.stdout.write(JSON.stringify(out));
