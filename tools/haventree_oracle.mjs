// Runs Haventree Bank's own prepayment calculator code (its Next.js/Turbopack chunk with the MortgageCalculator
// component, unmodified). React is replaced by a stand-in whose useCallback hands back the component's own charge
// function; inputs and the bank's reinvestment-rate table are passed exactly as the page passes them.
// Usage: node tools/haventree_oracle.mjs < cases.json
// case: {balance, contract, years, months, reinvestmentRates:[{minMonths,maxMonths,rate}]}  (maxMonths null = Infinity)
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "haventree_oracle", "mortgage-calculator-chunk.js"), "utf8");

let callbacks = [];
const React = { useState: (v) => [v, () => {}], useCallback: (fn) => (callbacks.push(fn), fn), useMemo: (fn) => fn(),
  useEffect: () => {}, useRef: (v) => ({ current: v }), useId: () => "id" };
const jsx = { jsx: () => null, jsxs: () => null, Fragment: {} };
const stub = new Proxy({}, { get: () => () => null });
const ctx = vm.createContext({ console: { log() {}, warn() {}, error() {} } });
vm.runInContext("globalThis.TURBOPACK = [];", ctx);
vm.runInContext(src, ctx);
const exportsByName = {};
for (const entry of ctx.TURBOPACK) {
  for (let k = 1; k + 1 < entry.length; k += 2) {
    const factory = entry[k + 1];
    if (typeof factory !== "function") continue;
    const e = { i: (id) => (id === 71645 ? React : id === 43476 ? jsx : stub),
                s: (arr) => { for (let n = 0; n + 2 < arr.length + 1; n += 3) if (typeof arr[n] === "string") exportsByName[arr[n]] = arr[n + 2]; },
                r: () => stub, n: (x) => x, v: () => {}, m: { exports: {} } };
    try { factory(e); } catch (err) { /* other modules in the chunk may need more of the page */ }
  }
}
const MortgageCalculator = exportsByName.MortgageCalculator;
if (typeof MortgageCalculator !== "function") throw new Error("MortgageCalculator not found in chunk");

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  callbacks = [];
  const rates = c.reinvestmentRates.map((r) => ({ ...r, maxMonths: r.maxMonths == null ? Infinity : r.maxMonths }));
  MortgageCalculator({ formData: { formFields: [] }, calculatorHeadingData: {}, reinvestmentRates: rates, locale: "en-CA" });
  const input = { remainingPrincipalBalance: c.balance, currentInterestRate: c.contract,
                  termsRemainingYears: c.years, termsRemainingMonths: c.months };
  let res = null;
  for (const fn of callbacks) {
    try { const r = fn(input); if (r && "estimatedPrepaymentCharge" in r) { res = r; break; } } catch (err) { }
  }
  out.push(res ? { charge: Math.round(100 * res.estimatedPrepaymentCharge) / 100, rate: res.reinvestmentRate,
                   three: res.threeMonthsInterest, ird: res.interestRateDifferential } : { charge: null });
}
process.stdout.write(JSON.stringify(out));
