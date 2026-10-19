// Runs ATB Financial's own mortgage prepayment penalty calculator (Vue app bundle + its vendor bundle, unmodified).
// A tiny webpack loader evaluates ATB's modules; Vue itself is replaced by a stand-in that captures the calculator
// component, whose own data / computed / methods (and module-level helpers) then compute the penalty.
// Usage: node tools/atb_oracle.mjs < cases.json
// case: {balance, contract, posted_original, prepayment:"YYYY-MM-DD", start:"YYYY-MM-DD", maturity:"YYYY-MM-DD", rates:[GetMppcRates rows]}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const dir = path.join(here, "..", "data", "ratewatch", "atb_oracle");
const vendors = fs.readFileSync(path.join(dir, "mpp-calculator.chunk-vendors.js"), "utf8");
const app = fs.readFileSync(path.join(dir, "mpp-calculator.app.js"), "utf8");

// module 8844 (the app) cut verbatim from the app bundle's module table
const start = app.indexOf("8844:function(t,e,a){");
let i = app.indexOf("{", start + "8844:function(t,e,a)".length), depth = 0, j = i, q = null, esc = false;
for (;; j++) {
  const ch = app[j];
  if (q) { if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === q) q = null; }
  else if (ch === '"' || ch === "'" || ch === "`") q = ch;
  else if (ch === "{") depth++;
  else if (ch === "}" && --depth === 0) break;
}
const appBody = app.slice(i + 1, j);

const captured = [];
function FakeVue(opts) { captured.push(opts); }
FakeVue.component = () => {}; FakeVue.use = () => {}; FakeVue.extend = (o) => o; FakeVue.config = {};

const ctx = vm.createContext({ console: { log() {}, warn() {}, error() {} }, Math, Date, JSON, Array, Object, Number,
  String, Symbol, Promise, Error, TypeError, RegExp, parseFloat, parseInt, isNaN, isFinite, setTimeout, clearTimeout });
{ const g = vm.runInContext("globalThis", ctx); ctx.self = g; ctx.window = g; }
vm.runInContext(vendors, ctx);
const modules = {};
for (const chunk of ctx.webpackChunkmortgage_penalty_calculator) Object.assign(modules, chunk[1]);
const cache = {};
function req(id) {
  if (id === 6848) return { Ay: FakeVue };                       // Vue: replaced by the capturing stand-in
  if (cache[id]) return cache[id].exports;
  const mod = (cache[id] = { id, loaded: false, exports: {} });
  modules[id].call(mod.exports, mod, mod.exports, req);
  mod.loaded = true;
  return mod.exports;
}
req.d = (e, defs) => { for (const k in defs) if (!Object.prototype.hasOwnProperty.call(e, k)) Object.defineProperty(e, k, { enumerable: true, get: defs[k] }); };
req.n = (m) => { const g = m && m.__esModule ? () => m["default"] : () => m; req.d(g, { a: g }); return g; };
req.o = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
req.g = vm.runInContext("globalThis", ctx); req.nmd = (m) => { m.paths = []; m.children ||= []; return m; };
req.r = (e) => { Object.defineProperty(e, "__esModule", { value: true }); };
ctx.__req = req;
const appFn = vm.runInContext("(function(t,e,a){" + appBody + "\n})", ctx);
appFn.call({}, { exports: {} }, {}, req);

const root = captured[0];
const App = root.render((c) => c);
const Calc = App.components.MortgagePrepaymentPenaltyCalculator;
const moment = req.n(req(9148))();

function instance(opts, props) {
  const inst = { ...props };
  Object.assign(inst, opts.data.call(inst));
  for (const [k, fn] of Object.entries(opts.methods || {})) inst[k] = fn.bind(inst);
  for (const [k, c] of Object.entries(opts.computed || {})) {
    const get = typeof c === "function" ? c : c.get;
    Object.defineProperty(inst, k, { get: () => get.call(inst), configurable: true, enumerable: true });
  }
  return inst;
}

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  ctx.location = { hostname: "www.atb.com", origin: "https://www.atb.com" };
  ctx.fetch = async () => ({ ok: true, json: async () => c.rates });
  const v = instance(Calc, { date: "2020-01-01", debug: false });
  Calc.created.call(v);
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  const m = (s) => moment.utc(s);
  v.mortgageTypeData.mortgageTypeP = "Residential Mortgage Loan";
  v.mortgageKindData.mortgageKindP = "Closed Fixed";
  v.paymentTypeData.paymentTypeP = "Full";
  v.mortgageBalanceData.mortgageBalanceP = c.balance;
  v.mortgageDateData.termStartDateP = m(c.start);
  v.mortgageDateData.termMaturityDateP = m(c.maturity);
  v.mortgageDateData.prepaymentDateP = m(c.prepayment);
  // ATB's own date step decides "started before the no-discount transition" from the typed start date
  const dateStep = instance(Calc.components.MortgageDate, { paymentTypeData: v.paymentTypeData, mortgageDateData: v.mortgageDateData });
  dateStep.termStartDateR = c.start;
  v.mortgageDateData.startedDuringNoBull = dateStep.startedDuringNoBull;
  v.remainingDetailsData.currentInterestRateR = String(c.contract);
  v.remainingDetailsData.postedInterestRateR = String(c.posted_original);
  // the child component that computes the penalty, wired with the same props the parent template passes
  const Details = Calc.components.RemainingDetails;
  const d = instance(Details, { mortgageTypeData: v.mortgageTypeData, mortgageKindData: v.mortgageKindData,
    paymentTypeData: v.paymentTypeData, mortgageDateData: v.mortgageDateData, mortgageBalanceData: v.mortgageBalanceData,
    cashbackData: v.cashbackData, mortgageValueData: v.mortgageValueData, previousPrepaymentsData: v.previousPrepaymentsData,
    currentPrepaymentData: v.currentPrepaymentData, remainingDetailsData: v.remainingDetailsData, rates: v.rates,
    debugging: false });
  let charge;
  try { charge = d.interestPenalty; } catch (err) { charge = null; }
  out.push({ charge: charge == null ? null : Math.round(100 * charge) / 100, raw: charge, rates: (v.rates || []).length });
}
process.stdout.write(JSON.stringify(out));
