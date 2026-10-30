// Runs Tangerine's own mortgage prepayment-charge calculator script (unmodified) inside a minimal fake page.
// The page script reads inputs by element id, receives rates through a CURRENT_RATES_LOADED event, and writes the
// charge into #cmp-mppc-prepayment-charge when the Calculate button is clicked.
// Usage: node tools/tangerine_oracle.mjs < cases.json
// case: {balance, contract, years, months, term_years, frequency, rates:{"1":r,"2":r,"3":r,"4":r,"5":r,"7":r,"10":r}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "tangerine_oracle", "mortgagePrePayment-calculator.js"), "utf8");

function makePage() {
  const els = new Map(), docHandlers = {};
  const el = (id) => {
    if (!els.has(id)) {
      const handlers = {};
      const e = { id, value: "", textContent: "", disabled: false, checked: false, style: {}, handlers,
        classList: { add() {}, remove() {}, contains() { return false; } },
        addEventListener(t, fn) { (handlers[t] ||= []).push(fn); },
        removeEventListener() {}, setAttribute() {}, getAttribute() { return null; }, focus() {},
        querySelectorAll() { return []; }, querySelector() { return null; } };
      for (let i = 0; i < 8; i++) e[i] = { selected: false };   // <select> options by position
      e.cloneNode = () => e;
      e.parentNode = { replaceChild() {} };
      els.set(id, e);
    }
    return els.get(id);
  };
  const html = { getAttribute: (k) => (k === "lang" ? "en-CA" : null) };
  const document = {
    readyState: "complete", getElementById: el,
    querySelector: (q) => (q === "html" ? html : null), querySelectorAll: () => [],
    addEventListener(t, fn) { (docHandlers[t] ||= []).push(fn); }, createElement: () => el("_tmp"),
  };
  return { els, el, document, docHandlers };
}

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const page = makePage();
  const ctx = vm.createContext({ document: page.document, window: { location: { port: "" } }, setTimeout: () => 0,
    console: { log() {}, warn() {}, error() {} }, Math, Number, String, parseFloat, parseInt, isNaN, Symbol });
  ctx.window.document = page.document;
  vm.runInContext(src, ctx);
  const detail = {};
  for (const [y, r] of Object.entries(c.rates)) detail[`MRTG.RATE.${y}_YEAR`] = String(r);
  page.el("cmp-mppc-mortgage-calcWrapper");
  (page.docHandlers["CURRENT_RATES_LOADED"] || []).forEach((fn) => fn({ detail }));
  const set = (id, v) => { page.el(id).value = String(v); };
  const fire = (id) => ["change", "input", "keyup", "blur"].forEach((t) =>
    (page.el(id).handlers[t] || []).forEach((fn) => fn({ target: page.el(id), preventDefault() {} })));
  const pick = (id, i) => { const e = page.el(id); for (let k = 0; k < 8; k++) e[k].selected = k === i; };
  // in the order a person fills the form: mortgage type (resets the rest), then "pay off the whole mortgage"
  pick("form-options-mppc-mortgage-type", 1); set("form-options-mppc-mortgage-type", 10); fire("form-options-mppc-mortgage-type");
  pick("form-options-mppc-prepaying", 2); set("form-options-mppc-prepaying", 53); fire("form-options-mppc-prepaying");
  set("form-options-mppc-term", c.term_years); fire("form-options-mppc-term");
  set("form-text-interest-rate", c.contract);
  set("form-options-mppc-payment-frequency", c.frequency || 12); fire("form-options-mppc-payment-frequency");
  set("form-text-due", c.balance);
  set("form-text-remaining-year", c.years);
  set("form-text-remaining-months", c.months);
  const btn = page.el("form-button-mppc-calculate");
  (btn.handlers.click || []).forEach((fn) => fn({ preventDefault() {} }));
  const txt = page.el("cmp-mppc-prepayment-charge").textContent;
  out.push({ charge: txt ? parseFloat(txt.replace(/[$,\s]/g, "")) : null, text: txt });
}
process.stdout.write(JSON.stringify(out));
