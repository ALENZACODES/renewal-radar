// Runs Equitable Bank's own single-family residential prepayment calculator code (its Next.js/Turbopack chunk):
// the date-helper module (1759) is evaluated through a minimal Turbopack loader, and the calculator module's helper
// prelude plus its charge function (the submit handler's calculation, which switches on mortgage type) are cut
// verbatim and evaluated with those helpers. Nothing in the math is changed.
// Usage: node tools/equitable_oracle.mjs < cases.json
// case: {balance, contract, discount, type:"standardFixed"|"esFixed", today:"YYYY-MM-DD", maturity:"YYYY-MM-DD",
//        reference:{standardFixed:{tBill,bond24,bond36,bond60}, esFixed:{"12":r,"24":r,"36":r,"48":r,"60":r}}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "equitable_oracle", "calculator-chunk.js"), "utf8");

function braceEnd(s, open) {
  let depth = 0, q = null, esc = false;
  for (let j = open; j < s.length; j++) {
    const ch = s[j];
    if (q) { if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === q) q = null; continue; }
    if (ch === '"' || ch === "'" || ch === "`") q = ch;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return j;
  }
  throw new Error("unbalanced");
}
// 1. date helpers: module 1759 exports {r, C, z, G, N, m}
const h0 = src.indexOf("1759,48243,35594,e=>{");
if (h0 < 0) throw new Error("Equitable chunk changed: date helper module not found");
const hOpen = src.indexOf("{", h0), hEnd = braceEnd(src, hOpen);
const helperFactory = vm.runInNewContext("(e=>" + src.slice(hOpen, hEnd + 1) + ")", { Date, Math, Number });
const helpers = {};
helperFactory({ i: () => ({ createElement: () => null }), s: (arr) => {
  for (let n = 0; n + 2 < arr.length + 1; n += 3) if (typeof arr[n] === "string") helpers[arr[n]] = arr[n + 2];
} });
// 2. calculator module prelude (d, p, f, m, h, g, v, y and the 2018 cut-over date c), verbatim
const p0 = src.indexOf("let c=new Date(2018,5,25);");
const p1 = src.indexOf('function y(e){return"partial"===e}', p0);
if (p0 < 0 || p1 < 0) throw new Error("Equitable chunk changed: calculator helpers not found");
const prelude = src.slice(p0, p1) + 'function y(e){return"partial"===e}';
// 3. the charge function passed to the result setter, verbatim
const f0 = src.indexOf("function(e,t,r=new Date){let{maturityDate:n,inceptionDate:a}=");
if (f0 < 0) throw new Error("Equitable chunk changed: charge function not found");
const fOpen = src.indexOf("{", f0), fEnd = braceEnd(src, fOpen);
const chargeFn = src.slice(f0, fEnd + 1);
const ctx = vm.createContext({ Date, Math, Number, Error, l: helpers, u: { D: (x, n) => Math.round(x * 10 ** n) / 10 ** n } });
const calc = vm.runInContext(prelude + "\n;(" + chargeFn + ")", ctx);

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const [ty, tm, td] = c.today.split("-").map(Number), [my, mm, md] = c.maturity.split("-").map(Number);
  const state = { mortgageType: c.type || "standardFixed", prepaymentType: "fullPayout", outstandingBalance: c.balance,
                  annualRate: c.contract, rateDiscount: c.discount || 0, maturityDay: md, maturityMonth: mm, maturityYear: my };
  const ref = { standardFixed: c.reference.standardFixed, esFixed: c.reference.esFixed || {} };
  const r = calc(state, ref, new Date(ty, tm - 1, td));
  out.push({ charge: Math.round(100 * r.charge) / 100, type: r.calculationType, bucket: r.referenceRateBucket,
             months: r.remainingMonths });
}
process.stdout.write(JSON.stringify(out));
