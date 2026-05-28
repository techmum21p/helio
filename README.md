# Data Sources

## What you need to download manually: almost nothing

psgc handles admin boundaries, population, and income classification.
GEE handles solar irradiance.

The only setup required is API authentication.

---

## 1. Google Earth Engine (one-time setup)

```bash
pip install earthengine-api
earthengine authenticate        # opens browser — link your Google account
earthengine set_project <your-gcp-project-id>
```

- Sign up: https://earthengine.google.com/signup (free, non-commercial)
- Set GCP project ID in `.env` as `GEE_PROJECT_ID`
- GEE datasets used:
  - `NASA/POWER/V9/DAILY` → solar irradiance (GHI)

---

## 2. psgc (pip install, no download)

```bash
pip install psgc[geo]
```

Gives you out of the box:
- 42,011 barangays, 1,656 cities, 83 provinces, 18 regions
- 2024 Census population per barangay
- PSGC income classification per city/municipality
- Lat/lon centroids (87% real, 13% inherited from parent)
- Fuzzy + phonetic Filipino search
- GeoJSON export directly into GeoPandas

No CSV, no shapefile, no manual download.

---

## Use QGIS for validation (optional but recommended)

If you want to visually inspect barangay coverage or spot-check
GEE irradiance outputs before trusting the pipeline:

1. Export GeoJSON from psgc:
   `psgc export --format geojson --level municipality --region "Region IV-A" -o calabarzon.geojson`
2. Open in QGIS
3. Overlay with GEE irradiance raster (add as WMS or import GeoTIFF)
4. Spot-check that scores look geographically sensible

This is optional — the pipeline runs without it.
