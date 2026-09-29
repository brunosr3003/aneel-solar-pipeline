#!/usr/bin/env python3
"""Load the filtered CSVs into a typed SQLite database.

Usage: build_db.py FILTERED_DIR DB_PATH

ANEEL numbers use decimal commas ("32,50"). Loading them as text and summing in
SQLite silently truncates every value to its integer part, so numeric columns
are converted here: Mda* (measures), Qtd* (counts) and NumCoord* (coordinates)
become REAL, and Dat*/Dth* columns become ISO dates.
"""
import csv
import sqlite3
import sys
from pathlib import Path

from aneel_io import DELIMITER, to_date, to_float

TABLES = {
    "gd_solar": ("gd-solar.csv", ["CodEmpreendimento", "NomMunicipio", "CodMunicipioIbge"]),
    "gd_solar_technical": ("gd-solar-technical.csv", ["CodGeracaoDistribuida", "DatConexao"]),
    "siga_solar": ("siga-solar.csv", ["CodCEG"]),
}


def column_kind(name):
    if name.startswith(("Mda", "Qtd", "NumCoord")):
        return "REAL"
    if name.startswith(("Dat", "Dth")):
        return "DATE"
    return "TEXT"


def convert(kind, value):
    if kind == "REAL":
        return to_float(value)
    if kind == "DATE":
        d = to_date(value)
        return d.isoformat() if d else None
    value = (value or "").strip()
    return value or None


def load_table(con, table, csv_path, indexes):
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = csv.DictReader(f, delimiter=DELIMITER)
        cols = rows.fieldnames
        kinds = [column_kind(c) for c in cols]
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} (" + ", ".join(
            f'"{c}" {"REAL" if k == "REAL" else "TEXT"}' for c, k in zip(cols, kinds)) + ")")
        placeholders = ", ".join("?" for _ in cols)
        batch, n = [], 0
        for row in rows:
            batch.append([convert(k, row[c]) for c, k in zip(cols, kinds)])
            if len(batch) >= 10_000:
                con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", batch)
                n += len(batch)
                batch.clear()
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", batch)
        n += len(batch)
    for col in indexes:
        if col in cols:
            con.execute(f'CREATE INDEX idx_{table}_{col} ON {table} ("{col}")')
    print(f"  {table}: {n:,} rows")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, db_path = Path(sys.argv[1]), Path(sys.argv[2])
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    for table, (fname, indexes) in TABLES.items():
        load_table(con, table, src / fname, indexes)
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(db_path)  # atomic swap: readers never see a half-built database
    print(f"Database written to {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
