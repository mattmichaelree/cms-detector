"""End-to-end acceptance demo: a citation-bearing dossier for one bill.

Pulls whatever the ingested corpus holds for the bill across source families
(TLO history, fiscal notes, HRO analysis, witness slips, journal votes) and
renders a joined text dossier. Sources not yet ingested simply report absent —
the demo degrades honestly rather than fabricating.
"""

from __future__ import annotations

import sqlite3


def _section(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}\n"


def build_dossier(conn: sqlite3.Connection, session: str, bill: str) -> str:
    bid = f"{session}-{bill.replace(' ', '').upper()}"
    out = [f"DOSSIER {bid}"]

    row = conn.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone()
    if not row:
        # Try to ingest live via TLO before giving up.
        from lobbybook.core.registry import get

        get("tlo").ingest_bill(conn, session, bill.replace(" ", ""))
        row = conn.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone()
    if not row:
        return f"{bid}: not in corpus and TLO ingest failed"

    out.append(f"Caption: {row['caption'] or '(none captured)'}")

    authors = conn.execute(
        "SELECT role, name_raw FROM bill_author WHERE bill_id=? ORDER BY role", (bid,)
    ).fetchall()
    if authors:
        out.append("Authors: " + "; ".join(f"{a['name_raw']} ({a['role']})" for a in authors))

    subjects = conn.execute("SELECT subject_code, subject_text FROM bill_subject WHERE bill_id=?", (bid,)).fetchall()
    if subjects:
        out.append("Subjects: " + "; ".join(
            f"{s['subject_text']}" + (f" [{s['subject_code']}]" if s["subject_code"] else "")
            for s in subjects))

    actions = conn.execute(
        "SELECT date, chamber, description FROM bill_action WHERE bill_id=? ORDER BY seq", (bid,)
    ).fetchall()
    out.append(_section(f"Actions ({len(actions)}) — source: TLO history, class A"))
    for a in actions[-15:]:
        out.append(f"  {a['date'] or '':<11} {a['chamber'] or ' '}  {a['description']}")
    if len(actions) > 15:
        out.insert(-15, f"  … {len(actions) - 15} earlier actions omitted")

    fns = conn.execute(
        "SELECT id, version_code, date, summary FROM fiscal_note WHERE bill_id=? ORDER BY date",
        (bid,),
    ).fetchall()
    out.append(_section(f"Fiscal notes ({len(fns)}) — LBB estimate, per bill version"))
    for f in fns:
        out.append(f"  [{f['version_code']}] {f['date'] or ''} {(f['summary'] or '')[:100]}")
    if not fns:
        out.append("  (none ingested)")
    # The version trap made visible: the same bill costs different money at
    # different stages, so a figure cited without its version is wrong.
    if len(fns) > 1:
        totals = []
        for f in fns:
            tot = conn.execute(
                """SELECT SUM(amount) s FROM fiscal_estimate
                   WHERE fiscal_note_id=? AND fund LIKE '%General Revenue%'""",
                (f["id"],),
            ).fetchone()["s"]
            if tot is not None:
                totals.append((f["version_code"], tot))
        if len(totals) > 1 and len({round(t, 2) for _, t in totals}) > 1:
            out.append("\n  ** version trap: General Revenue estimates differ by stage **")
            for code, tot in totals:
                out.append(f"     {code}: {tot:>20,.0f}")
            out.append("     Citing 'the fiscal note' without a version code misstates this bill.")

    slips = conn.execute(
        """SELECT position, testified, COUNT(*) n FROM witness_slip WHERE bill_id=?
           GROUP BY position, testified ORDER BY position""",
        (bid,),
    ).fetchall()
    out.append(_section("Witness registrations — committee records, class A (positions)"))
    if slips:
        for s in slips:
            kind = "testified" if s["testified"] else "registered only"
            out.append(f"  {s['position']:<8} {kind:<15} {s['n']}")
        lean = {p: 0 for p in ("for", "against", "on")}
        for s in slips:
            lean[s["position"]] = lean.get(s["position"], 0) + s["n"]
        if lean["for"] or lean["against"]:
            ratio = (
                f"{lean['against'] / lean['for']:.0f}:1 against"
                if lean["for"] and lean["against"] > lean["for"]
                else f"{lean['for'] / max(lean['against'], 1):.0f}:1 for"
            )
            out.append(f"\n  Registration lean: {lean['for']} for / {lean['against']} against ({ratio})")
            out.append("  Registrations are a mobilization signal, not a vote count.")
        orgs = conn.execute(
            """SELECT org_raw, COUNT(*) n FROM witness_slip
               WHERE bill_id=? AND org_raw IS NOT NULL AND org_raw != ''
               GROUP BY org_raw ORDER BY n DESC LIMIT 5""",
            (bid,),
        ).fetchall()
        if orgs:
            out.append("  Most-represented organizations: "
                       + "; ".join(f"{o['org_raw']} ({o['n']})" for o in orgs))
    else:
        out.append("  (none ingested)")

    votes = conn.execute(
        """SELECT v.id, v.chamber, v.date, v.record_no, v.yeas, v.nays, v.journal_cite
           FROM vote v WHERE v.bill_id=? ORDER BY v.date""",
        (bid,),
    ).fetchall()
    out.append(_section("Record votes — journals, class A"))
    for v in votes:
        out.append(
            f"  {v['date'] or '':<11} {v['chamber']} record {v['record_no'] or '?'}: "
            f"{v['yeas']}-{v['nays']}  (cite: {v['journal_cite'] or 'n/a'})"
        )
    if not votes:
        out.append("  (none ingested — note: absence of a record vote is not evidence of consent)")

    edges = conn.execute(
        "SELECT COUNT(*) n FROM edge WHERE (src_type='bill' AND src_id=?) OR (dst_type='bill' AND dst_id=?)",
        (bid, bid),
    ).fetchone()["n"]
    out.append(f"\nGraph edges touching this bill: {edges}")
    return "\n".join(out)
