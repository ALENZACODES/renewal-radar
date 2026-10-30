// Runs Scotiabank's own published prepayment-charge code (main.js, module "logic.js", unmodified) as a test oracle.
// Usage: node tools/scotia_oracle.mjs < cases.json > results.json
// Each case: {balance, original, contract, discount, months_remaining, term_months, rates: {"6":r, "12":r, ...}}
// Rates are percentages; Scotiabank's code works in decimals, so they are divided by 100 exactly as its UI does.
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const dir = path.join(here, "..", "data", "ratewatch", "scotia_oracle");
const src = fs.readFileSync(path.join(dir, "main.js"), "utf8");
const bands = JSON.parse(fs.readFileSync(path.join(dir, "termRates.json"), "utf8").replace(/^﻿/, "")).rates;

const start = src.indexOf('define("logic.js", function(require, exports, module) {');
if (start < 0) throw new Error("logic.js module not found in main.js");
const bodyStart = src.indexOf("{", start) + 1;
const end = src.indexOf('});define(', bodyStart);
const body = src.slice(bodyStart, end);

const SERVER_TERM = { "6F": 6, "1C": 12, "2C": 24, "3C": 36, "4C": 48, "5C": 60, "7C": 84, "10C": 120 };
// Scotiabank's dropdown codes for fixed terms (getOriginalTermInMonths): code -> months
const TERM_CODE = { 6: 0, 12: 2, 24: 4, 36: 5, 48: 6, 60: 7, 84: 8, 120: 9 };

let currentRates = bands;
const fakeRequire = (name) => {
  if (name.includes("utilities")) return { lang: "en" };
  if (name.includes("rates")) return { init: () => Promise.resolve(1), getAllRates: () => currentRates };
  return {};
};
const exports = {};
new Function("require", "exports", "module", body)(fakeRequire, exports, { exports });
await new Promise((r) => setTimeout(r, 0));          // let logic.js pick up `rates` from init()

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = [];
for (const c of cases) {
  currentRates.forEach((b) => { if (SERVER_TERM[b.serverMap] && c.rates[SERVER_TERM[b.serverMap]] != null) b.value = c.rates[SERVER_TERM[b.serverMap]]; });
  const r = exports.payoutPrepayLogic({
    originalMortgage: c.original, currentBalance: c.balance, prepayment: 0, rate: TERM_CODE[c.term_months],
    isFixed: true, isOpen: false, isPrepayment: false, monthsRemainingOnCurrentTerm: c.months_remaining,
    currentRate: c.contract / 100, discountRate: c.discount / 100, capRate: 0, cashback: 0,
    originalDate: new Date(2023, 0, 1),
  });
  out.push({ charge: Math.round(100 * r.charge) / 100, text: r.dynamicResultText });
}
process.stdout.write(JSON.stringify(out));
