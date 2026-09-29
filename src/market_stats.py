#!/usr/bin/env python3
"""Market-size statistics for distributed solar generation, from ANEEL data only.

Usage: market_stats.py DB_PATH OUT_DIR [--since YYYY-MM-DD] [--top 10]

Writes to OUT_DIR:
  municipalities.csv  per municipality: all-time and recent projects/kW, average system size
  summary.json        state totals, monthly connections, top module and inverter brands

"Recent" means connected on or after --since (default: 18 months ago).
Note: ANEEL does not identify the installer of each system, so these numbers
describe the whole market, not any single company's share of it.
"""
import argparse
import csv
import json
import sqlite3
from datetime import date
from pathlib import Path


def months_ago(n, today=None):
    today = today or date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    return date(y, m + 1, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--since", default=months_ago(18).isoformat())
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.db)

    joined = """FROM gd_solar s
        JOIN gd_solar_technical t ON t.CodGeracaoDistribuida = s.CodEmpreendimento"""

    rows = con.execute(f"""
        WITH total AS (
            SELECT NomMunicipio AS muni, COUNT(*) AS n, SUM(MdaPotenciaInstaladaKW) AS kw
            FROM gd_solar GROUP BY NomMunicipio),
        recent AS (
            SELECT s.NomMunicipio AS muni, COUNT(*) AS n, SUM(s.MdaPotenciaInstaladaKW) AS kw
            {joined} WHERE t.DatConexao >= ? GROUP BY s.NomMunicipio)
        SELECT total.muni, total.n, total.kw, COALESCE(recent.n, 0), COALESCE(recent.kw, 0)
        FROM total LEFT JOIN recent USING (muni)
        ORDER BY COALESCE(recent.n, 0) DESC""", (args.since,)).fetchall()

    with open(args.out_dir / "municipalities.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["municipality", "projects_total", "kw_total", "projects_recent", "kw_recent",
                    "avg_kw_recent"])
        for muni, n, kw, rn, rkw in rows:
            w.writerow([muni, n, round(kw or 0, 1), rn, round(rkw, 1), round(rkw / rn, 2) if rn else ""])

    def top(column):
        return [{"name": name, "projects": n} for name, n in con.execute(f"""
            SELECT UPPER(TRIM(t.{column})) AS name, COUNT(*) AS n {joined}
            WHERE t.DatConexao >= ? AND TRIM(COALESCE(t.{column}, '')) <> ''
            GROUP BY name ORDER BY n DESC LIMIT ?""", (args.since, args.top))]

    monthly = [{"month": m, "projects": n, "kw": round(kw or 0, 1)} for m, n, kw in con.execute(f"""
        SELECT substr(t.DatConexao, 1, 7) AS m, COUNT(*), SUM(s.MdaPotenciaInstaladaKW)
        {joined} WHERE t.DatConexao IS NOT NULL GROUP BY m ORDER BY m""")]

    total_n, total_kw = con.execute("SELECT COUNT(*), SUM(MdaPotenciaInstaladaKW) FROM gd_solar").fetchone()
    recent_n = sum(r[3] for r in rows)
    recent_kw = sum(r[4] for r in rows)
    utility = con.execute("SELECT COUNT(*), SUM(MdaPotenciaOutorgadaKw) FROM siga_solar").fetchone()

    summary = {
        "generated_on": date.today().isoformat(),
        "recent_since": args.since,
        "distributed_generation": {
            "projects_total": total_n, "kw_total": round(total_kw or 0, 1),
            "projects_recent": recent_n, "kw_recent": round(recent_kw, 1),
            "municipalities": len(rows),
        },
        "utility_scale_plants": {"plants": utility[0], "kw_granted": round(utility[1] or 0, 1)},
        "top_module_brands_recent": top("NomFabricanteModulo"),
        "top_inverter_brands_recent": top("NomFabricanteInversor"),
        "monthly_connections": monthly,
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    dg = summary["distributed_generation"]
    print(f"Distributed solar: {dg['projects_total']:,} projects, {dg['kw_total'] / 1000:,.1f} MW")
    print(f"Connected since {args.since}: {dg['projects_recent']:,} projects, {dg['kw_recent'] / 1000:,.1f} MW")
    print(f"Utility-scale plants: {utility[0]:,}")
    print("Top municipalities (recent):")
    for muni, _, _, rn, rkw in rows[:5]:
        print(f"  {muni:<24} {rn:>6,} projects  {rkw / 1000:>8,.1f} MW")


if __name__ == "__main__":
    main()
