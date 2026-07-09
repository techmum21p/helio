"""
Fetches real PSA income classification + census population data, sourced from
the yng-me/psgc R package (MIT license), which bundles the official PSA PSGC
publication data (income_classification) and census population figures
(2015 / 2020 / 2024) extracted from PSA releases.

PSA's own site (psa.gov.ph) blocks programmatic downloads behind Cloudflare,
so this pulls the pre-extracted R data object from GitHub instead and parses
it in pure Python via the `rdata` library (no R installation required).

Output: data/raw/psa_income_population.csv with columns:
    psgc_code, name, province, geographic_level, income_classification, population_2024

Usage:
    python scripts/fetch_psa_data.py                # uses cached download if present
    python scripts/fetch_psa_data.py --refresh       # re-downloads sysdata.rda
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import rdata
import requests

REPO_ROOT = Path(__file__).parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
RDA_PATH = RAW_DIR / "psgc_sysdata.rda"
OUT_PATH = RAW_DIR / "psa_income_population.csv"
SYSDATA_URL = "https://raw.githubusercontent.com/yng-me/psgc/main/R/sysdata.rda"
RELEASE = "Q1_2026"
POPULATION_YEAR = 2024


def download_sysdata(refresh: bool = False) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RDA_PATH.exists() and not refresh:
        print(f"Using cached {RDA_PATH}")
        return RDA_PATH
    print(f"Downloading {SYSDATA_URL} ...")
    resp = requests.get(SYSDATA_URL, timeout=60)
    resp.raise_for_status()
    RDA_PATH.write_bytes(resp.content)
    print(f"Saved to {RDA_PATH} ({len(resp.content):,} bytes)")
    return RDA_PATH


def build_dataset(rda_path: Path) -> pd.DataFrame:
    parsed = rdata.parser.parse_file(str(rda_path))
    converted = rdata.conversion.convert(parsed)

    releases = converted["psgc_releases"][RELEASE]
    population = converted["psgc_population"][RELEASE]
    population = population[population["year"] == POPULATION_YEAR][["psgc_code", "population"]]

    # PSGC code layout: 2-digit region + 3-digit province + 3-digit muni/city + 2-digit barangay.
    # Province prefix is therefore the first 5 characters, not 4 (a 4-char slice
    # silently collides different provinces within the same region, e.g. Aklan/Antique).
    provinces = releases[releases["geographic_level"] == "Prov"][["psgc_code", "area_name"]].copy()
    provinces["prov_prefix"] = provinces["psgc_code"].str[:5]
    prov_lookup = dict(zip(provinces["prov_prefix"], provinces["area_name"]))

    munis = releases[releases["geographic_level"].isin(["Mun", "City"])].copy()
    munis["province"] = munis["psgc_code"].str[:5].map(prov_lookup)

    munis = munis.merge(population, on="psgc_code", how="left")
    munis = munis.rename(columns={
        "area_name": "name",
        "income_classification": "income_classification",
        "population": "population_2024",
    })

    out = munis[[
        "psgc_code", "name", "province", "geographic_level",
        "income_classification", "population_2024",
    ]].reset_index(drop=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-download sysdata.rda even if cached")
    args = parser.parse_args()

    rda_path = download_sysdata(refresh=args.refresh)
    df = build_dataset(rda_path)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    n_income = df["income_classification"].notna().sum()
    n_pop = df["population_2024"].notna().sum()
    print(f"Wrote {len(df):,} municipality/city rows to {OUT_PATH}")
    print(f"  income_classification populated: {n_income:,} / {len(df):,}")
    print(f"  population_2024 populated:       {n_pop:,} / {len(df):,}")


if __name__ == "__main__":
    sys.exit(main())
