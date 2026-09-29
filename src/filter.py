#!/usr/bin/env python3
"""Filter the raw ANEEL datasets down to solar (UFV) projects in one state.

Usage: filter.py RAW_DIR OUT_DIR [--state MG] [--siga-since 2019] [--keep-personal-data]

Outputs (UTF-8, semicolon-separated):
  gd-solar.csv            distributed generation registry, one row per project
  gd-solar-technical.csv  technical details (modules, inverters, connection date)
  siga-solar.csv          utility-scale solar plants from SIGA
"""
import argparse
import csv
from pathlib import Path

from aneel_io import DELIMITER, open_aneel_csv, reader, to_date

GD_REGISTRY = "empreendimento-geracao-distribuida.csv"
GD_TECHNICAL = "empreendimento-gd-informacoes-tecnicas-fotovoltaica.csv"
SIGA = "siga-empreendimentos-geracao.csv"

# Owner identification published by ANEEL. Dropped by default: the analysis does
# not need it, and it includes individuals' CPF numbers (personal data under LGPD).
PERSONAL_COLUMNS = {"NumCPFCNPJ", "NomTitularEmpreendimento"}


def filter_csv(src, dst, predicate, label, drop=frozenset()):
    kept = total = 0
    with open_aneel_csv(src) as fin, open(dst, "w", encoding="utf-8", newline="") as fout:
        rows = reader(fin)
        fields = [f for f in rows.fieldnames if f not in drop]
        writer = csv.DictWriter(fout, fieldnames=fields, delimiter=DELIMITER, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            total += 1
            if predicate(row):
                writer.writerow(row)
                kept += 1
    print(f"  {label}: kept {kept:,} of {total:,} rows")
    return kept


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--state", default="MG", help="Brazilian state code (UF). Default: MG")
    ap.add_argument("--siga-since", type=int, default=2019,
                    help="Keep SIGA plants that started operating in or after this year. Default: 2019")
    ap.add_argument("--keep-personal-data", action="store_true",
                    help="Keep owner CPF/CNPJ and name columns (off by default)")
    args = ap.parse_args()

    state = args.state.upper()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    drop = frozenset() if args.keep_personal_data else PERSONAL_COLUMNS

    print(f"== 1/3 Distributed generation registry ({state}, solar) ==")
    project_ids = set()

    def gd_pred(row):
        if row.get("SigUF") != state or row.get("SigTipoGeracao") != "UFV":
            return False
        if row.get("CodEmpreendimento"):
            project_ids.add(row["CodEmpreendimento"])
        return True

    filter_csv(args.raw_dir / GD_REGISTRY, args.out_dir / "gd-solar.csv", gd_pred, "registry", drop)
    print(f"  unique project ids: {len(project_ids):,}")

    # The technical dataset has no state column; it is joined through the project id.
    print("== 2/3 Distributed generation technical data ==")
    filter_csv(args.raw_dir / GD_TECHNICAL, args.out_dir / "gd-solar-technical.csv",
               lambda row: row.get("CodGeracaoDistribuida") in project_ids, "technical", drop)

    print(f"== 3/3 SIGA utility-scale plants ({state}, solar, since {args.siga_since}) ==")

    def siga_pred(row):
        if row.get("SigUFPrincipal") != state or row.get("SigTipoGeracao") != "UFV":
            return False
        started = to_date(row.get("DatEntradaOperacao"))
        # Plants without a start date are still under construction: keep them.
        return started is None or started.year >= args.siga_since

    filter_csv(args.raw_dir / SIGA, args.out_dir / "siga-solar.csv", siga_pred, "SIGA", drop)

    print("\nOutput files:")
    for p in sorted(args.out_dir.glob("*.csv")):
        print(f"  {p.name}: {p.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
