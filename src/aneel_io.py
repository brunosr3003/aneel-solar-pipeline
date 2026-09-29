"""Helpers for reading ANEEL open-data CSV files.

ANEEL publishes semicolon-separated CSVs with decimal commas. Two things changed
around 2026-08 without notice: the larger files are now served as ZIP archives
while keeping the `.csv` name, and the encoding moved from Latin-1 to UTF-8.
Every reader here sniffs both before opening the file.
"""
import csv
import io
import sys
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

csv.field_size_limit(sys.maxsize)

DELIMITER = ";"
SNIFF_BYTES = 1 << 20


def _detect_encoding(sample):
    # Drop the last partial line so a multi-byte character cut in half is not misread.
    sample = sample[: sample.rfind(b"\n") + 1] or sample
    try:
        sample.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "latin-1"


@contextmanager
def open_aneel_csv(path):
    """Yield a text stream for an ANEEL CSV, unzipping and detecting the encoding as needed."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"{path}: expected exactly one CSV inside the ZIP, found {members}")
            with zf.open(members[0]) as raw:
                encoding = _detect_encoding(raw.read(SNIFF_BYTES))
            with zf.open(members[0]) as raw:
                yield io.TextIOWrapper(raw, encoding=encoding, newline="")
    else:
        with open(path, "rb") as raw:
            encoding = _detect_encoding(raw.read(SNIFF_BYTES))
        with open(path, encoding=encoding, newline="") as f:
            yield f


def reader(stream):
    return csv.DictReader(stream, delimiter=DELIMITER)


def to_float(value):
    """Parse ANEEL numbers ("1.234,56" or "32,50"). Returns None for blanks."""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return float(s)
    except ValueError:
        return None


def to_date(value):
    """Parse the date formats found across ANEEL datasets. Returns None when unparseable."""
    if not value:
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
