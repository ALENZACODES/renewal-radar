// Runs Desjardins' own prepayment-penalty calculator code (calculateur-indemnites-calculs.js, unmodified) as an oracle.
// Usage: TZ=UTC node tools/desjardins_oracle.mjs < cases.json
// case: {balance, contract, discount, term_months, today:"YYYY-MM-DD", maturity:"YYYY-MM-DD", rates:{"12":r,...,"120":r}}
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const src = fs.readFileSync(path.join(here, "..", "data", "ratewatch", "desjardins_oracle", "calculateur-indemnites-calculs.js"), "utf8");
// TypePret is a constants table from the page's app.js; the calculation file only compares against it.
const ctx = vm.createContext({ TypePret: { PRET_TAUX_FIXE: "PRET_TAUX_FIXE", PRET_TAUX_VAR: "PRET_TAUX_VAR",
  PRET_TAUX_ANN: "PRET_TAUX_ANN", PRET_TAUX_PROTEGE: "PRET_TAUX_PROTEGE" }, console, Math, Date, parseFloat });
vm.runInContext(src + "\n;globalThis.DesjOCI = DesjOCI;", ctx);
const D = ctx.DesjOCI;
const NAMES = { 12: "1_an", 24: "2_ans", 36: "3_ans", 48: "4_ans", 60: "5_ans", 72: "6_ans", 84: "7_ans", 120: "10_ans" };
const out = [];
for (const c of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const fixe = {};
  for (const [t, n] of Object.entries(NAMES)) fixe["terme_" + n] = { ferme: c.rates[t] };
  const [ty, tm, td] = c.today.split("-").map(Number);
  const [my, mm, md] = c.maturity.split("-").map(Number);
  const scenario = { pret_complet_solde_hypo_actuel: c.balance, pret_complet_terme_duree: c.term_months,
    pret_complet_type: "PRET_TAUX_FIXE", pret_complet_echeance_annee: my, pret_complet_echeance_mois: mm,
    pret_complet_echeance_jour: md, taux_interet_hypo: c.contract, rabais_taux_supp: c.discount, avec_remise: "NON",
    montant_remise: 0, date_de_simulation: new Date(ty, tm - 1, td).setHours(0, 0, 0, 0) };
  const r = D.getIndemniteComplet(scenario, { fixe });
  out.push({ charge: Math.round(100 * r.indemnite_montant_total) / 100, ird: r.indemnite_ecart_taux, three: r.indemnite_3mois,
             term: r.taux_duree_restante_terme, months: r.duree_restante_terme_mois });
}
process.stdout.write(JSON.stringify(out));
