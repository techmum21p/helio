from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # kept for fallback reference
XIAOMI_API_KEY = os.getenv("XIAOMI_TOKEN_PLAN_KEY")
XIAOMI_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/anthropic"  # Default base URL
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# Google Earth Engine
# Your GCP project ID with Earth Engine API enabled
# Free for non-commercial use: https://earthengine.google.com/signup
GEE_PROJECT_ID = os.getenv("GEE_PROJECT_ID", "your-gcp-project-id")

# Paths
ROOT_DIR = Path(__file__).parent
DATA_RAW = ROOT_DIR / "data" / "raw"
DATA_PROCESSED = ROOT_DIR / "data" / "processed"
KB_DIR = ROOT_DIR / "kb"
KB_REPORTS = KB_DIR / "reports"
KB_INTEL = KB_DIR / "intel"
REPORTS_DIR = ROOT_DIR / "reports"
SESSIONS_DIR = ROOT_DIR / "sessions"
LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"

# Create dirs if missing
for d in [DATA_RAW, DATA_PROCESSED, KB_REPORTS, KB_INTEL, REPORTS_DIR, SESSIONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# Model config
REPORT_MODEL = os.getenv("REPORT_MODEL", "mimo-v2.5")
CHATBOT_MODEL = os.getenv("CHATBOT_MODEL", "mimo-v2.5")

# Scoring weights (must sum to 1.0)
WEIGHTS = {
    "solar":      0.35,   # was 0.40
    "income":     0.45,   # was 0.35
    "population": 0.20,   # was 0.25; now applied to pop_density
}

# Final score blend weights
FINAL_GEO_WEIGHT = 0.70   # was 0.80
FINAL_WEB_WEIGHT = 0.30   # was 0.20

# Consolidated DB (helio.db replaces ph_locations.db for all structured data)
HELIO_DB = ROOT_DIR / "data" / "helio.db"

# Pipeline config
TOP_N_TARGETS = int(os.getenv("TOP_N_TARGETS", 20))
MAX_WEB_RESULTS = int(os.getenv("MAX_WEB_RESULTS", 5))
WEB_INTEL_CACHE_TTL_DAYS = int(os.getenv("WEB_INTEL_CACHE_TTL_DAYS", 30))
