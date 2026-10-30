// Runs Laurentian Bank's own fixed-rate prepayment-penalty computation, cut verbatim from its Next.js chunk
// (the calculator's submit handler, from reading the form to the charge `j`). The page's clock is fixed to noon on
// the review date and its locale number parser is replaced by a plain one; nothing in the math is changed.
// Usage: TZ=UTC node tools/laurentian_oracle.mjs < cases.json
// case: {balance, contract, posted, frequency:0|1|2 (monthly|biweekly|weekly), today:"YYYY-MM-DD", maturity:"YYYY-MM-DD",
//        reference:{sixMonths, oneYear, twoYears, ..., tenYears}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "laurentian_oracle", "calculator-chunk.js"), "utf8");
const from = "let{maturityDate:e,paymentFrequency:n,annualInterestRate:t,postedRate:l,remainingLoanBalance:a}=I.fixedRateForm,";
const to = ",A=np(j,q);";
const a0 = src.indexOf(from), b0 = src.indexOf(to, a0);
if (a0 < 0 || b0 < 0) throw new Error("Laurentian chunk changed: fixed-rate computation not found");
const body = src.slice(a0, b0);

const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const [y, m, d] = c.today.split("-").map(Number);
  const NOW = new Date(y, m - 1, d, 12, 0, 0).getTime();
  class FixedDate extends Date { constructor(...args) { if (args.length) super(...args); else super(NOW); } }
  const ctx = vm.createContext({ Math, Date: FixedDate, nb: ({ value }) => Number(value) });
  const run = vm.runInContext(`(function(I, L, q){ ${body}; return {j, i, u, h}; })`, ctx);
  const [my, mm, md] = c.maturity.split("-").map(Number);
  const form = { maturityDate: { value: new Date(my, mm - 1, md) }, paymentFrequency: { value: c.frequency || 0 },
                 annualInterestRate: { value: String(c.contract) }, postedRate: { value: String(c.posted) },
                 remainingLoanBalance: { value: String(c.balance) } };
  const r = run({ fixedRateForm: form }, c.reference, "en");
  out.push({ charge: Math.round(100 * r.j) / 100, months: r.u, ref: r.h });
}
process.stdout.write(JSON.stringify(out));
