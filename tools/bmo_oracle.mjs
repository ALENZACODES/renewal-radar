// Runs BMO's own published prepayment-charge code as a test oracle: the term lookup y() and the pay-in-full charge
// expression are cut verbatim out of BMO's calculator bundle (app.js) and evaluated with the UI calls stubbed.
// Usage: node tools/bmo_oracle.mjs < cases.json
// Each case: {balance, contract, discount, months, rates: {"6":r,"12":r,"24":r,"36":r,"48":r,"60":r,"72":r,"84":r,"120":r}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "bmo_oracle", "app.js"), "utf8");
const cut = (from, to) => {
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error("BMO bundle changed: cannot find " + from.slice(0, 40));
  return src.slice(a, b);
};
const yFn = cut("function y(e,t){var a=0,o=6,n=!1;", "switch(t.s3lumpsumBack") ;
const charge = cut("var g=0;if(o.b.dispatch(Object(r.k)(\"calcswitch1month\",!1))", ",a.prepaymentCharge=");
const ctx = vm.createContext({ o: { b: { dispatch() {} } }, r: { k() {} }, Object, Number, Math });
vm.runInContext(yFn, ctx);
const run = new vm.Script(`(function(i,s,l){${charge};return g})`).runInContext(ctx);

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const table = Object.entries(c.rates).map(([m, r]) => ({ months: String(m), rate: String(r) }));
  const s = ctx.y(c.months, table);
  const i = { rateType: ["fixed rate"], currentRate: c.contract, rateDiscountAmount: c.discount, mortgageBalance: c.balance };
  const g = run(i, s, c.months);
  out.push({ charge: Math.round(100 * g) / 100, posted: s });
}
process.stdout.write(JSON.stringify(out));
