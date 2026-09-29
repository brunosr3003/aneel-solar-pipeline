# aneel-solar-pipeline

A daily data pipeline that turns the raw open data from **ANEEL** (Brazil's electricity regulator) into a clean, typed SQLite database and market statistics for solar generation in a Brazilian state.

It downloads three public datasets (about 4.6 million rows and 1.5 GB uncompressed), keeps only the solar projects of one state, joins registry and technical data, and produces per-municipality numbers you can query, chart or browse with [Datasette](https://datasette.io). It uses only the Python standard library, with no dependencies to install.

```
$ DATA_DIR=./data scripts/pipeline.sh
[1/5] Downloading 3 datasets in parallel...
[2/5] Filtering solar projects in MG...
  registry: kept 484,691 of 4,656,839 rows
  technical: kept 484,691 of 4,655,916 rows
  SIGA: kept 219 of 25,133 rows
[3/5] Building SQLite database...
[4/5] Computing market statistics...
Distributed solar: 484,691 projects, 6,398.7 MW
Connected since 2025-03-01: 114,471 projects, 1,287.6 MW
Top municipalities (recent):
  Uberlândia                4,443 projects      26.0 MW
  Governador Valadares      3,816 projects      26.2 MW
  Belo Horizonte            3,688 projects      31.9 MW
```
<sub>Real output for Minas Gerais, run on 2026-09-29.</sub>

## Data sources

All data comes from the [ANEEL open data portal](https://dadosabertos.aneel.gov.br), published under an open license and refreshed by ANEEL roughly daily.

| Dataset | What it contains | Key fields |
|---|---|---|
| [Distributed generation registry](https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2) (`empreendimento-geracao-distribuida.csv`) | Every distributed generation project in Brazil (rooftop and small ground-mounted systems under net metering): state, municipality, utility, consumer class, generation type, installed power | `CodEmpreendimento`, `SigUF`, `SigTipoGeracao`, `NomMunicipio`, `MdaPotenciaInstaladaKW` |
| [Distributed generation — PV technical data](https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2) (`empreendimento-gd-informacoes-tecnicas-fotovoltaica.csv`) | Module and inverter manufacturers and models, number of modules, array area and **grid connection date** of each PV project | `CodGeracaoDistribuida`, `DatConexao`, `NomFabricanteModulo`, `NomFabricanteInversor` |
| [SIGA — generation plants](https://dadosabertos.aneel.gov.br/dataset/6d90b77c-c5f5-4d81-bdec-7bc619494bb9) (`siga-empreendimentos-geracao.csv`) | Utility-scale plants of every source, with phase (operating, under construction), grant type and granted power | `CodCEG`, `SigUFPrincipal`, `SigTipoGeracao`, `DatEntradaOperacao`, `MdaPotenciaOutorgadaKw` |

### How the datasets fit together

- Solar is `SigTipoGeracao = 'UFV'` (*usina fotovoltaica*) in both the registry and SIGA.
- The technical dataset has **no state column**. It is linked to the registry through `CodGeracaoDistribuida = CodEmpreendimento`, so the filter collects project ids from the registry first and then keeps the matching technical rows.
- The connection date (`DatConexao`) only exists in the technical dataset. That is why "recent market" numbers need the join.

### Quirks this pipeline handles

These are the things that break naive scripts, found the hard way:

| Quirk | How it is handled |
|---|---|
| Since August 2026 the two large files are served as **ZIP archives while keeping the `.csv` name** | Files are sniffed and unzipped as a stream, with no temporary 1.5 GB file on disk |
| The encoding changed from **Latin-1 to UTF-8** at the same time, without notice | Encoding is detected from the first 1 MB of each file |
| Numbers use a **decimal comma** (`32,50`). Loaded as text, SQLite sums `'32,50'` as `32`, which undercounted installed power by about 1.5% | Converted to REAL when the database is built (`Mda*`, `Qtd*`, `NumCoord*` columns) |
| Dates come in several formats across datasets | Normalized to ISO `YYYY-MM-DD` |
| The ANEEL server often drops connections mid-download | `curl --retry-all-errors`, and the run stops if any download fails instead of processing a partial file |
| The registry publishes the **owner's CPF/CNPJ and name** | Dropped by default (personal data under LGPD). Use `--keep-personal-data` only if you have a legal basis |

One thing no pipeline can fix: **ANEEL does not record who installed each system**, so this data describes the whole market, not any single company's share of it.

## Usage

Requirements: Python 3.9+, `curl`, and about 1 GB of free disk space during a run.

```sh
git clone https://github.com/brunosr3003/aneel-solar-pipeline.git
cd aneel-solar-pipeline
scripts/pipeline.sh                # Minas Gerais into ./data
STATE=SP scripts/pipeline.sh       # any other state
```

| Variable | Default | Meaning |
|---|---|---|
| `STATE` | `MG` | Brazilian state code (UF) to keep |
| `DATA_DIR` | `./data` | Where downloads, filtered files, the database and stats are written |
| `RETAIN_DAYS` | `7` | Days of dated snapshots kept locally |
| `S3_TARGET` | *(unset)* | Optional [MinIO client](https://min.io/docs/minio/linux/reference/minio-mc.html) target such as `myminio/aneel-solar`. Filtered files and stats are uploaded there, with a stable `stats/latest/` copy |

Each step also runs on its own:

```sh
python3 src/filter.py RAW_DIR OUT_DIR --state MG --siga-since 2019
python3 src/build_db.py OUT_DIR data/aneel-solar.db
python3 src/market_stats.py data/aneel-solar.db data/stats --since 2025-01-01 --top 10
```

To refresh daily with cron:

```cron
0 6 * * * cd /path/to/aneel-solar-pipeline && scripts/pipeline.sh >/dev/null 2>&1
```

## Outputs

```
data/
├── raw/YYYY-MM-DD/          original ANEEL downloads
├── filtered/YYYY-MM-DD/     gd-solar.csv, gd-solar-technical.csv, siga-solar.csv (UTF-8)
├── aneel-solar.db           SQLite: gd_solar, gd_solar_technical, siga_solar (indexed)
├── stats/latest/
│   ├── municipalities.csv   per municipality: all-time and recent projects and kW, average system size
│   └── summary.json         state totals, monthly connections, top module and inverter brands
└── logs/
```

"Recent" means connected in the last 18 months by default (`--since` changes it).

### Browsing with Datasette

```sh
pip install datasette
datasette data/aneel-solar.db --metadata datasette-metadata.json
```

This gives a searchable web UI with facets by municipality, utility, consumer class and equipment brand.

## Project layout

```
scripts/pipeline.sh     orchestration: download → filter → SQLite → stats → upload → cleanup
src/aneel_io.py         ZIP and encoding detection, ANEEL number and date parsing
src/filter.py           state + solar filter, registry ↔ technical join, personal-data removal
src/build_db.py         typed SQLite build with an atomic swap
src/market_stats.py     per-municipality and state-level statistics
```

## License

Code: [MIT](LICENSE) © Bruno Soares Reis.
Data: published by ANEEL under its [open data terms](https://dadosabertos.aneel.gov.br). This project is not affiliated with ANEEL.
