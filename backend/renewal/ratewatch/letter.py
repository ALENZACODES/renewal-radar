"""Printable penalty assessment letter (PDF), formal-letter style in navy and crimson.

    python -m renewal.ratewatch.letter            -> data/ratewatch/letters/sample-penalty-letter.pdf
    from renewal.ratewatch.letter import build_letter

Issued by Renewal Radar (John Khan) to the homeowner. Colours: navy #011F5B, crimson #990000 (palette only, no third-party marks).
"""
from datetime import date
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from .paths import DATA

NAVY = colors.HexColor("#011F5B")
CRIMSON = colors.HexColor("#990000")
RULE = colors.HexColor("#C9CED8")
# Letterhead. Renewal Radar is built by John Khan; leave a field blank to hide it.
BROKER = {
    "name": "Renewal Radar",
    "title": "John Khan",
    "brokerage": "",
    "brokerage_no": "",
    "licence": "",
    "phone": "",
}


def _join(*parts, sep="  ·  "):
    return sep.join(p for p in parts if p)

BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=10.8, leading=14.2, alignment=TA_JUSTIFY, textColor=colors.HexColor("#1D2433"))
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.2, leading=11, textColor=colors.HexColor("#5B6170"))
HEAD = ParagraphStyle("head", parent=BODY, fontName="Times-Bold", fontSize=12.5, textColor=NAVY, spaceBefore=6, spaceAfter=4)


def _frame(canvas, doc):
    w, h = LETTER
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 1.05 * inch, w, 1.05 * inch, stroke=0, fill=1)
    canvas.setFillColor(CRIMSON)
    canvas.rect(0, h - 1.11 * inch, w, 0.06 * inch, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Bold", 21)
    canvas.drawString(0.85 * inch, h - 0.55 * inch, BROKER["name"])
    canvas.setFont("Times-Italic", 10.5)
    canvas.drawString(0.85 * inch, h - 0.8 * inch, _join(BROKER["title"], BROKER["brokerage"]))
    canvas.setFont("Times-Roman", 9)
    canvas.drawRightString(w - 0.85 * inch, h - 0.55 * inch, BROKER["phone"])
    canvas.drawRightString(w - 0.85 * inch, h - 0.8 * inch, _join(BROKER["brokerage_no"], BROKER["licence"]))
    canvas.setStrokeColor(CRIMSON)
    canvas.setLineWidth(0.8)
    canvas.line(0.85 * inch, 0.75 * inch, w - 0.85 * inch, 0.75 * inch)
    canvas.setFillColor(NAVY)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(0.85 * inch, 0.55 * inch, _join(BROKER["name"], BROKER["title"], BROKER["brokerage"], BROKER["brokerage_no"], BROKER["licence"], sep=" · "))
    canvas.drawRightString(w - 0.85 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _money(x):
    return f"${x:,.2f}"


TEXT = {
    "en": {
        "re": "Re: Prepayment penalty assessment, {lender} mortgage", "dear": "Dear {first},",
        "intro": ("Here is your Renewal Radar assessment of your {lender} mortgage. Based on the figures below, the estimated "
                  "cost to break your term on {day} is <b>{amount}</b>, calculated as {how}. Lenders charge the greater of the "
                  "two amounts shown."),
        "ird": "an interest rate differential (IRD)", "3mo": "three months' interest",
        "h1": "How the estimate is calculated", "h2": "When the charge changes", "h3": "Next steps",
        "rows": ["Item", "Value", "Balance", "Your contract rate", "Your original discount", "Months remaining",
                 "Lender's posted rate, {term}-month term", "Comparison rate (posted minus discount)", "Three months' interest",
                 "Interest rate differential", "Estimated prepayment charge"],
        "if": "If posted rates stay where they are today:",
        "change": "On {day} the lender starts comparing against its {term}-month rate; the estimate becomes <b>{amount}</b>.",
        "next": ("Request a dated written payout statement from your lender before making a decision; the lender's statement is "
                 "the final figure. Upload it to Renewal Radar to compare it against this estimate and to plan the timing of a "
                 "switch around the dates above."),
        "ok": "This lender's method was reproduced exactly from its published calculator.",
        "est": "This lender's method has not yet been verified against its payout statements; treat the figure as an estimate.",
        "fine": ("Estimate only. {basis} Posted rates are taken from the lender's published rates on the date shown. Fees such as "
                 "discharge, administration or cash-back repayment are not included."),
    },
    "fr": {
        "re": "Objet : évaluation de la pénalité de remboursement anticipé, prêt {lender}", "dear": "Bonjour {first},",
        "intro": ("Voici l’évaluation Renewal Radar de votre prêt {lender}. Selon les données ci-dessous, rompre votre terme le "
                  "{day} coûterait environ <b>{amount}</b>, calculé selon {how}. Le prêteur exige le plus élevé des deux montants."),
        "ird": "un différentiel de taux d’intérêt (DTI)", "3mo": "trois mois d’intérêts",
        "h1": "Calcul de l’estimation", "h2": "Quand la pénalité change", "h3": "Prochaines étapes",
        "rows": ["Élément", "Valeur", "Solde", "Votre taux contractuel", "Votre escompte initial", "Mois restants",
                 "Taux affiché du prêteur, terme de {term} mois", "Taux de comparaison (affiché moins escompte)",
                 "Trois mois d’intérêts", "Différentiel de taux d’intérêt (DTI)", "Pénalité estimée"],
        "if": "Si les taux affichés restent à leur niveau actuel :",
        "change": "Le {day}, le prêteur compare à son taux de {term} mois; l’estimation devient <b>{amount}</b>.",
        "next": ("Demandez à votre prêteur un relevé de remboursement écrit et daté avant de décider; ce relevé fait foi. "
                 "Téléversez-le dans Renewal Radar pour le comparer à cette estimation et planifier le moment d’un changement."),
        "ok": "La méthode de ce prêteur a été reproduite exactement à partir de son calculateur publié.",
        "est": "La méthode de ce prêteur n’a pas encore été validée; considérez ce montant comme une estimation.",
        "fine": ("Estimation seulement. {basis} Les taux affichés proviennent des taux publiés par le prêteur à la date indiquée. "
                 "Les frais (quittance, administration, remboursement de remise en argent) ne sont pas inclus."),
    },
}
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _day(d, lang):
    return f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}" if lang == "fr" else d.strftime("%B %d, %Y").replace(" 0", " ")


def _amt(x, lang):
    return f"{x:,.2f} $".replace(",", " ").replace(".", ",") if lang == "fr" else f"${x:,.2f}"


def _pct(x, lang):
    return f"{x:.2f} %".replace(".", ",") if lang == "fr" else f"{x:.2f}%"


def _x(text) -> str:
    """Escape user-supplied text: ReportLab treats <...> as markup (fonts, links, images), so nothing user-typed may
    reach Paragraph unescaped."""
    from xml.sax.saxutils import escape
    return escape(str(text), {'"': "&quot;", "'": "&#39;"})


def build_letter(out_path, client, mortgage, result, forecast_rows=None, lender_verified=False, today=None, language="en"):
    """client: {name, address_lines}; mortgage: {lender, balance, contract_rate};
    result: dict from ird.penalty(); forecast_rows: list from ird.forecast() (optional); language: en | fr."""
    lang = "fr" if language == "fr" else "en"
    T = TEXT[lang]
    today = today or date.today()
    if result.get("method") == "matured":
        raise ValueError("term has matured: there is no prepayment charge to explain")
    doc = SimpleDocTemplate(out_path if hasattr(out_path, "write") else str(out_path), pagesize=LETTER, leftMargin=0.85 * inch, rightMargin=0.85 * inch,
                            topMargin=1.4 * inch, bottomMargin=0.95 * inch, title="Prepayment Penalty Assessment",
                            author="John Khan", subject="Mortgage prepayment penalty assessment", creator="Renewal Radar")
    s = [Paragraph(_day(today, lang), BODY), Spacer(1, 10)]
    name = (str(client.get("name") or "").strip() or "Homeowner")[:120]
    lender = str(mortgage["lender"])[:60]
    s += [Paragraph(f"<b>{_x(name)}</b><br/>" + "<br/>".join(_x(a)[:200] for a in client.get("address_lines", [])), BODY), Spacer(1, 12)]
    s.append(Paragraph(f'<font color="#990000"><b>{T["re"].format(lender=_x(lender))}</b></font>', BODY))
    s += [Spacer(1, 10), Paragraph(T["dear"].format(first=_x(name.split()[0])), BODY), Spacer(1, 6)]
    s.append(Paragraph(T["intro"].format(lender=_x(lender), day=_day(date.fromisoformat(result["payout"]), lang),
                                         amount=_amt(result["penalty"], lang), how=T["ird"] if result["method"] == "IRD" else T["3mo"]), BODY))
    s += [Spacer(1, 10), Paragraph(T["h1"], HEAD)]
    L = T["rows"]
    rows = [[L[0], L[1]],
            [L[2], _amt(mortgage["balance"], lang)],
            [L[3], _pct(mortgage["contract_rate"], lang)],
            [L[4], _pct(result["discount"], lang)],
            [L[5], f"{result['remaining_months']:.2f}".replace(".", "," if lang == "fr" else ".")],
            [L[6].format(term=result["compare_term"]), _pct(result["compare_posted"], lang)],
            [L[7], _pct(result["compare_rate"], lang)],
            [L[8], _amt(result["three_month"], lang)],
            [L[9], _amt(result["ird"], lang)],
            [L[10], _amt(result["penalty"], lang)]]
    t = Table(rows, colWidths=[4.3 * inch, 2.4 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Times-Bold", 10.5), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("FONT", (0, 1), (-1, -1), "Times-Roman", 10.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("FONT", (0, -1), (-1, -1), "Times-Bold", 11), ("TEXTCOLOR", (0, -1), (-1, -1), CRIMSON),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, CRIMSON), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    s.append(t)
    if forecast_rows:
        changes = [r for r in forecast_rows if r.get("transition")]
        if changes:
            s += [Spacer(1, 12), Paragraph(T["h2"], HEAD)]
            lines = "".join("<br/>• " + T["change"].format(day=_day(date.fromisoformat(r["payout"]), lang), term=r["compare_term"],
                                                           amount=_amt(r["penalty"], lang)) for r in changes[:4])
            s.append(Paragraph(T["if"] + lines, BODY))
    s += [Spacer(1, 12), Paragraph(T["h3"], HEAD), Paragraph(T["next"], BODY), Spacer(1, 10)]
    s.append(Paragraph(T["fine"].format(basis=T["ok"] if lender_verified else T["est"]), SMALL))
    doc.build(s, onFirstPage=_frame, onLaterPages=_frame)
    return out_path


def sample(language="en"):
    from .ird import Mortgage, POLICIES, forecast, penalty
    today = date.today()
    table = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.0, maturity=date(2028, 10, 15))
    r = penalty(m, POLICIES["TD"], table, today)
    f = forecast(m, POLICIES["TD"], table, today)
    out = DATA / "letters"
    out.mkdir(exist_ok=True)
    return build_letter(out / f"sample-penalty-letter-{language}.pdf",
                        {"name": "Alex Sample", "address_lines": ["100 Example Street", "Toronto, ON  M5V 0A1"]},
                        {"lender": "TD", "balance": 400_000, "contract_rate": 4.89}, r, f,
                        lender_verified=POLICIES["TD"].verified, language=language)


if __name__ == "__main__":
    print(sample("en"))
    print(sample("fr"))
