"""Build the mission catalog from CDAWeb REST API.

Queries CDAWeb's dataset catalog XML, groups datasets by observatory/mission,
categorizes by InstrumentType, and writes one JSON per mission.

Usage:
    python -m cdawebmcp.scripts.build_catalog              # Build all
    python -m cdawebmcp.scripts.build_catalog --mission psp # Build one
    python -m cdawebmcp.scripts.build_catalog --discover    # Show unmatched datasets
"""

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from cdawebmcp.http import request_with_retry

logger = logging.getLogger(__name__)

# Output directory for mission JSONs
MISSIONS_DIR = Path(__file__).parent.parent / "data" / "missions"

# CDAWeb REST API endpoints
CDAWEB_REST_URL = (
    "https://cdaweb.gsfc.nasa.gov/WS/cdasr/1/dataviews/sp_phys/datasets"
)
_NS = {"cda": "http://cdaweb.gsfc.nasa.gov/schema"}


# ===================================================================
# Mission prefix map (CDAWeb entries only — no PDS URN prefixes)
# ===================================================================

MISSION_PREFIX_MAP = {
    # --- Parker Solar Probe ---
    "PSP_FLD": ("psp", "FIELDS/MAG"),
    "PSP_SWP_SPC": ("psp", "SWEAP"),
    "PSP_SWP_SPI": ("psp", "SWEAP/SPAN-I"),
    "PSP_SWP_SPA": ("psp", "SWEAP/SPAN-E"),
    "PSP_SWP_SPB": ("psp", "SWEAP/SPAN-E"),
    "PSP_SWP": ("psp", "SWEAP"),
    "PSP_ISOIS": ("psp", "ISOIS"),
    "PSP_": ("psp", None),
    # --- Solar Orbiter ---
    "SOLO_L2_MAG": ("solo", "MAG"),
    "SOLO_L2_SWA": ("solo", "SWA-PAS"),
    "SOLO_": ("solo", None),
    "SO_": ("solo", None),
    # --- ACE ---
    "AC_H": ("ace", None),
    "AC_K": ("ace", None),
    "AC_OR": ("ace", None),
    "AC_AT": ("ace", None),
    # --- OMNI ---
    "OMNI_HRO": ("omni", "Combined"),
    "OMNI_": ("omni", "Combined"),
    "OMNI2_": ("omni", "Combined"),
    # --- Wind ---
    "WIND_": ("wind", None),
    "WI_H": ("wind", None),
    "WI_K": ("wind", None),
    "WI_OR": ("wind", None),
    "WI_AT": ("wind", None),
    "WI_": ("wind", None),
    # --- DSCOVR ---
    "DSCOVR_H0_MAG": ("dscovr", "MAG"),
    "DSCOVR_H1_FC": ("dscovr", "FC"),
    "DSCOVR_": ("dscovr", None),
    # --- MMS ---
    "MMS1_FGM": ("mms", "FGM"),
    "MMS1_FPI": ("mms", "FPI-DIS"),
    "MMS2_FGM": ("mms", "FGM"),
    "MMS2_FPI": ("mms", "FPI-DIS"),
    "MMS3_FGM": ("mms", "FGM"),
    "MMS3_FPI": ("mms", "FPI-DIS"),
    "MMS4_FGM": ("mms", "FGM"),
    "MMS4_FPI": ("mms", "FPI-DIS"),
    "MMS1_": ("mms", None),
    "MMS2_": ("mms", None),
    "MMS3_": ("mms", None),
    "MMS4_": ("mms", None),
    # --- STEREO ---
    "STA_L2_MAG": ("stereo_a", "MAG"),
    "STA_L2_PLA": ("stereo_a", "PLASTIC"),
    "STA_L1_MAG": ("stereo_a", "MAG"),
    "STA_L1_PLA": ("stereo_a", "PLASTIC"),
    "STA_": ("stereo_a", None),
    "STB_L2_MAG": ("stereo_b", None),
    "STB_L2_PLA": ("stereo_b", None),
    "STB_L1_MAG": ("stereo_b", None),
    "STB_L1_PLA": ("stereo_b", None),
    "STB_": ("stereo_b", None),
    "STEREO_": ("stereo_a", None),
    # --- THEMIS ---
    "THAPRED_": ("themis", None),
    "THBPRED_": ("themis", None),
    "THCPRED_": ("themis", None),
    "THDPRED_": ("themis", None),
    "THEPRED_": ("themis", None),
    "THG_": ("themis", None),
    "THA_L2": ("themis", None), "THA_L1": ("themis", None),
    "THB_L2": ("themis", None), "THB_L1": ("themis", None),
    "THC_L2": ("themis", None), "THC_L1": ("themis", None),
    "THD_L2": ("themis", None), "THD_L1": ("themis", None),
    "THE_L2": ("themis", None), "THE_L1": ("themis", None),
    "THA_": ("themis", None), "THB_": ("themis", None),
    "THC_": ("themis", None), "THD_": ("themis", None),
    "THE_": ("themis", None), "TH_": ("themis", None),
    # --- Cluster ---
    "C1_CP": ("cluster", None), "C2_CP": ("cluster", None),
    "C3_CP": ("cluster", None), "C4_CP": ("cluster", None),
    "C1_": ("cluster", None), "C2_": ("cluster", None),
    "C3_": ("cluster", None), "C4_": ("cluster", None),
    "CL_": ("cluster", None),
    # --- Van Allen Probes / RBSP ---
    "RBSP-A-RBSPICE": ("rbsp", None), "RBSP-B-RBSPICE": ("rbsp", None),
    "RBSP-A": ("rbsp", None), "RBSP-B": ("rbsp", None),
    "RBSPA_": ("rbsp", None), "RBSPB_": ("rbsp", None),
    "RBSP_": ("rbsp", None),
    # --- GOES ---
    "GOES10_": ("goes", None), "GOES11_": ("goes", None),
    "GOES12_": ("goes", None), "GOES13_": ("goes", None),
    "GOES14_": ("goes", None), "GOES15_": ("goes", None),
    "GOES16_": ("goes", None), "GOES17_": ("goes", None),
    "GOES18_": ("goes", None), "GOES_": ("goes", None),
    "G0_": ("goes", None),
    "G6_": ("goes", None), "G7_": ("goes", None),
    "G8_": ("goes", None), "G9_": ("goes", None),
    "G10_": ("goes", None), "G11_": ("goes", None),
    "G12_": ("goes", None), "G13_": ("goes", None),
    "G14_": ("goes", None), "G15_": ("goes", None),
    "G16_": ("goes", None), "G17_": ("goes", None),
    "G18_": ("goes", None),
    # --- Voyager ---
    "VG1_": ("voyager1", None), "VG2_": ("voyager2", None),
    "VOYAGER-1": ("voyager1", None), "VOYAGER-2": ("voyager2", None),
    "VOYAGER1_": ("voyager1", None), "VOYAGER2_": ("voyager2", None),
    # --- Ulysses ---
    "UY_": ("ulysses", None), "ULYSSES_": ("ulysses", None),
    # --- Other missions ---
    "GE_": ("geotail", None),
    "PO_": ("polar", None), "POLAR_": ("polar", None),
    "IM_": ("image", None), "IMAGE_": ("image", None),
    "FA_": ("fast", None), "FAST_": ("fast", None),
    "SOHO_": ("soho", None),
    "JUNO_": ("juno", None),
    "MVN_": ("maven", None), "MAVEN_": ("maven", None),
    "MESS_": ("messenger", None), "MESSENGER_": ("messenger", None),
    "CO_": ("cassini", None), "CASSINI_": ("cassini", None),
    "NEW-HORIZONS": ("new_horizons", None),
    "NEW_HORIZONS": ("new_horizons", None), "NH_": ("new_horizons", None),
    "I8_": ("imp8", None), "I1_": ("imp8", None),
    "I2_": ("imp8", None), "IA_": ("imp8", None),
    "ISEE": ("isee", None),
    "ERG_": ("arase", None), "ARASE_": ("arase", None),
    "TIMED_": ("timed", None),
    "TWINS1_": ("twins", None), "TWINS2_": ("twins", None), "TWINS_": ("twins", None),
    "IBEX_": ("ibex", None),
    "SAMPEX_": ("sampex", None), "SE_": ("sampex", None),
    "BARREL_": ("barrel", None), "BAR_": ("barrel", None),
    "CNOFS_": ("cnofs", None),
    "DMSP": ("dmsp", None),
    "LANL_": ("lanl", None),
    "L0_": ("lanl", None), "L1_": ("lanl", None),
    "L4_": ("lanl", None), "L7_": ("lanl", None),
    "L9_": ("lanl", None), "A1_": ("lanl", None), "A2_": ("lanl", None),
    "AMPTECCE": ("ampte", None), "AMPTE_": ("ampte", None),
    "HAWKEYE_": ("hawkeye", None),
    "HELIOS1_": ("helios", None), "HELIOS2_": ("helios", None),
    "HEL1_": ("helios", None), "HEL2_": ("helios", None),
    "PIONEER10_": ("pioneer", None), "PIONEER11_": ("pioneer", None),
    "P10_": ("pioneer", None), "P11_": ("pioneer", None),
    "SNOE_": ("snoe", None),
    "SWARM": ("swarm", None),
    "ICON_": ("icon", None),
    "GOLD_": ("gold", None),
    "EL": ("elfin", None),
    "EQ_": ("equator_s", None),
    "DE1_": ("de", None), "DE2_": ("de", None), "DE_": ("de", None),
    "PIONEERVENUS_": ("pioneer_venus", None),
    "NOAA05_": ("noaa", None), "NOAA06_": ("noaa", None),
    "NOAA07_": ("noaa", None), "NOAA08_": ("noaa", None),
    "NOAA10_": ("noaa", None), "NOAA12_": ("noaa", None),
    "NOAA14_": ("noaa", None), "NOAA15_": ("noaa", None),
    "NOAA16_": ("noaa", None), "NOAA18_": ("noaa", None),
    "NOAA19_": ("noaa", None),
    "METOP": ("noaa", None),
    "CRRES_": ("crres", None),
    "GPS_": ("gps", None),
    "ISS_": ("iss", None),
    "CIRBE_": ("cirbe", None),
    "CSSWE_": ("csswe", None),
    "ST5-": ("st5", None),
}


MISSION_NAMES = {
    "psp": "Parker Solar Probe",
    "solo": "Solar Orbiter",
    "ace": "ACE",
    "omni": "OMNI",
    "wind": "Wind",
    "dscovr": "DSCOVR Deep Space Climate Observatory",
    "mms": "MMS Magnetospheric Multiscale",
    "stereo_a": "STEREO-A",
    "stereo_b": "STEREO-B",
    "themis": "THEMIS",
    "cluster": "Cluster",
    "rbsp": "Van Allen Probes",
    "goes": "GOES",
    "voyager1": "Voyager 1",
    "voyager2": "Voyager 2",
    "ulysses": "Ulysses",
    "geotail": "Geotail",
    "polar": "Polar",
    "image": "IMAGE",
    "fast": "FAST",
    "soho": "SOHO",
    "juno": "Juno",
    "maven": "MAVEN",
    "messenger": "MESSENGER",
    "cassini": "Cassini",
    "new_horizons": "New Horizons",
    "imp8": "IMP-8",
    "isee": "ISEE",
    "arase": "Arase/ERG",
    "timed": "TIMED",
    "twins": "TWINS",
    "ibex": "IBEX",
    "sampex": "SAMPEX",
    "barrel": "BARREL",
    "cnofs": "C/NOFS",
    "dmsp": "DMSP",
    "lanl": "LANL",
    "ampte": "AMPTE",
    "hawkeye": "Hawkeye",
    "helios": "Helios",
    "pioneer": "Pioneer",
    "snoe": "SNOE",
    "swarm": "Swarm",
    "icon": "ICON",
    "gold": "GOLD",
    "elfin": "ELFIN",
    "equator_s": "Equator-S",
    "de": "Dynamics Explorer",
    "pioneer_venus": "Pioneer Venus",
    "noaa": "NOAA POES",
    "crres": "CRRES",
    "gps": "GPS",
    "iss": "ISS",
    "cirbe": "CIRBE",
    "csswe": "CSSWE",
    "st5": "ST5",
}


# ===================================================================
# Instrument type mapping (from CDAWeb InstrumentType taxonomy)
# ===================================================================

INSTRUMENT_TYPE_INFO = {
    "Magnetic Fields (space)": {
        "id": "mag", "name": "Magnetic Fields",
        "keywords": ["magnetic", "field", "mag", "b-field", "imf", "magnetometer"],
    },
    "Plasma and Solar Wind": {
        "id": "plasma", "name": "Plasma and Solar Wind",
        "keywords": ["plasma", "solar wind", "proton", "density", "velocity",
                      "temperature", "ion", "electron"],
    },
    "Particles (space)": {
        "id": "particles", "name": "Energetic Particles",
        "keywords": ["particle", "energetic", "cosmic ray"],
    },
    "Electric Fields (space)": {
        "id": "efield", "name": "Electric Fields",
        "keywords": ["electric", "e-field"],
    },
    "Radio and Plasma Waves (space)": {
        "id": "waves", "name": "Radio and Plasma Waves",
        "keywords": ["radio", "wave", "plasma wave"],
    },
    "Activity Indices": {
        "id": "indices", "name": "Activity Indices",
        "keywords": ["index", "indices", "geomagnetic", "sym-h", "dst", "kp", "ae"],
    },
    "Ephemeris/Attitude/Ancillary": {
        "id": "ephemeris", "name": "Ephemeris and Attitude",
        "keywords": ["ephemeris", "orbit", "attitude", "position"],
    },
    "Ground-Based Magnetometers, Riometers, Sounders": {
        "id": "ground_mag", "name": "Ground-Based Magnetometers",
        "keywords": ["ground", "magnetometer", "riometer"],
    },
    "Imaging and Remote Sensing (Magnetosphere/Earth)": {
        "id": "imaging_mag", "name": "Magnetospheric Imaging",
        "keywords": ["imaging", "remote sensing", "magnetosphere"],
    },
    "Imaging and Remote Sensing (ITM/Earth)": {
        "id": "imaging_itm", "name": "ITM Imaging",
        "keywords": ["imaging", "ionosphere", "thermosphere", "mesosphere"],
    },
    "Imaging and Remote Sensing (Sun)": {
        "id": "imaging_sun", "name": "Solar Imaging",
        "keywords": ["solar", "coronagraph", "euv", "uv", "x-ray"],
    },
    "Engineering": {
        "id": "engineering", "name": "Engineering",
        "keywords": ["engineering", "housekeeping"],
    },
    "Housekeeping": {
        "id": "engineering", "name": "Engineering",
        "keywords": ["engineering", "housekeeping"],
    },
    "Plasma Composition/Charge State Analyzers": {
        "id": "composition", "name": "Plasma Composition",
        "keywords": ["composition", "charge state", "ion"],
    },
    "Coronagraph/Heliograph": {
        "id": "coronagraph", "name": "Coronagraph",
        "keywords": ["coronagraph", "heliograph", "solar"],
    },
}

INSTRUMENT_TYPE_PRIORITY = [
    "Magnetic Fields (space)",
    "Plasma and Solar Wind",
    "Particles (space)",
    "Electric Fields (space)",
    "Radio and Plasma Waves (space)",
    "Activity Indices",
    "Plasma Composition/Charge State Analyzers",
    "Coronagraph/Heliograph",
    "Imaging and Remote Sensing (Sun)",
    "Imaging and Remote Sensing (Magnetosphere/Earth)",
    "Imaging and Remote Sensing (ITM/Earth)",
    "Ground-Based Magnetometers, Riometers, Sounders",
    "Engineering",
    "Housekeeping",
    "Ephemeris/Attitude/Ancillary",
]


# ===================================================================
# Helper functions
# ===================================================================


def match_dataset_to_mission(dataset_id: str) -> tuple[str | None, str | None]:
    """Map a CDAWeb dataset ID to (mission_stem, instrument_hint)."""
    for prefix, (mission, instrument) in MISSION_PREFIX_MAP.items():
        if dataset_id.startswith(prefix):
            return mission, instrument
    return None, None


def pick_primary_type(instrument_types: list[str]) -> str | None:
    """Pick the highest-priority InstrumentType from a list."""
    if not instrument_types:
        return None
    for priority_type in INSTRUMENT_TYPE_PRIORITY:
        if priority_type in instrument_types:
            return priority_type
    return instrument_types[0] if instrument_types else None


def get_type_info(instrument_type: str) -> dict:
    """Return {id, name, keywords} for an InstrumentType string."""
    info = INSTRUMENT_TYPE_INFO.get(instrument_type)
    if info:
        return dict(info)
    clean_id = instrument_type.lower().replace(" ", "_").replace("/", "_")
    clean_id = clean_id.replace("(", "").replace(")", "")
    return {"id": clean_id, "name": instrument_type, "keywords": []}


def get_canonical_id(mission_stem: str) -> str:
    """Return the canonical mission ID for a stem."""
    _CANONICAL = {
        "solo": "SolO",
        "stereo_a": "STEREO_A",
        "stereo_b": "STEREO_B",
    }
    if mission_stem in _CANONICAL:
        return _CANONICAL[mission_stem]
    if "_" in mission_stem:
        return mission_stem.upper().replace("_", "-")
    return mission_stem.upper()


def create_mission_skeleton(mission_stem: str) -> dict:
    """Create a minimal mission JSON skeleton."""
    name = MISSION_NAMES.get(mission_stem, mission_stem.upper())
    return {
        "id": get_canonical_id(mission_stem),
        "name": name,
        "profile": {
            "description": f"{name} data from CDAWeb.",
            "coordinate_systems": [],
            "typical_cadence": "",
            "data_caveats": [],
        },
        "instruments": {},
    }


# ===================================================================
# CDAWeb REST API
# ===================================================================


def _text(elem, tag: str) -> str:
    """Extract text from a child element, or empty string."""
    child = elem.find(tag, _NS)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def fetch_cdaweb_catalog() -> dict[str, dict]:
    """Fetch all dataset metadata from CDAWeb REST API.

    Returns dict mapping dataset_id to metadata.
    """
    print("Fetching dataset catalog from CDAWeb REST API...")
    resp = request_with_retry(CDAWEB_REST_URL)

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"Error parsing CDAWeb XML: {e}")
        return {}

    result = {}
    for ds in root.findall("cda:DatasetDescription", _NS):
        ds_id = _text(ds, "cda:Id")
        if not ds_id:
            continue

        instrument_types = [
            el.text.strip()
            for el in ds.findall("cda:InstrumentType", _NS)
            if el.text and el.text.strip()
        ]

        ti = ds.find("cda:TimeInterval", _NS)
        start_date = ""
        stop_date = ""
        if ti is not None:
            start_date = _text(ti, "cda:Start")
            stop_date = _text(ti, "cda:End")

        result[ds_id] = {
            "instrument": _text(ds, "cda:Instrument") or "",
            "instrument_types": instrument_types,
            "label": _text(ds, "cda:Label") or "",
            "observatory": _text(ds, "cda:Observatory") or "",
            "pi_name": _text(ds, "cda:PiName") or "",
            "doi": _text(ds, "cda:Doi") or "",
            "start_date": start_date,
            "stop_date": stop_date,
        }

    print(f"  Found {len(result)} datasets")
    return result


# ===================================================================
# Mission JSON building
# ===================================================================


def build_mission_json(mission_stem: str, catalog: dict[str, dict]) -> dict:
    """Build a complete mission JSON from CDAWeb catalog data.

    Args:
        mission_stem: Lowercase mission identifier (e.g., 'psp', 'ace').
        catalog: Full CDAWeb catalog from fetch_cdaweb_catalog().

    Returns:
        Mission dict ready to write as JSON.
    """
    mission = create_mission_skeleton(mission_stem)

    # Find all datasets belonging to this mission
    matched = []
    for ds_id, ds_meta in catalog.items():
        ds_mission, ds_instrument_hint = match_dataset_to_mission(ds_id)
        if ds_mission == mission_stem:
            matched.append((ds_id, ds_meta, ds_instrument_hint))

    print(f"  {mission['name']}: {len(matched)} datasets")

    for ds_id, ds_meta, instrument_hint in matched:
        # Determine instrument category
        primary_type = pick_primary_type(ds_meta.get("instrument_types", []))
        if primary_type:
            type_info = get_type_info(primary_type)
            inst_id = type_info["id"]
            inst_name = type_info["name"]
            inst_keywords = type_info["keywords"]
        elif instrument_hint:
            inst_id = instrument_hint
            inst_name = instrument_hint
            inst_keywords = []
        else:
            inst_id = "General"
            inst_name = "General"
            inst_keywords = []

        # Ensure instrument exists
        if inst_id not in mission["instruments"]:
            mission["instruments"][inst_id] = {
                "name": inst_name,
                "keywords": inst_keywords,
                "datasets": {},
            }

        # Add dataset
        ds_entry = {
            "description": ds_meta.get("label", ""),
            "start_date": ds_meta.get("start_date", ""),
            "stop_date": ds_meta.get("stop_date", ""),
        }
        if ds_meta.get("pi_name"):
            ds_entry["pi_name"] = ds_meta["pi_name"]
        if ds_meta.get("doi"):
            ds_entry["doi"] = ds_meta["doi"]

        mission["instruments"][inst_id]["datasets"][ds_id] = ds_entry

    # Add generation metadata
    mission["_meta"] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "CDAWeb REST API",
    }

    return mission


def save_mission_json(mission_stem: str, data: dict):
    """Save a mission JSON file."""
    MISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = MISSIONS_DIR / f"{mission_stem}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    print(f"  Saved {filepath.name}")


def discover_unmatched(catalog: dict[str, dict]):
    """Show CDAWeb datasets that don't match any known mission prefix."""
    unmatched = []
    for ds_id in catalog:
        mission, _ = match_dataset_to_mission(ds_id)
        if mission is None:
            unmatched.append(ds_id)

    print(f"\n{len(unmatched)} datasets not matched to any mission:")
    prefixes: dict[str, list[str]] = {}
    for ds_id in unmatched:
        prefix = ds_id.split("_")[0] if "_" in ds_id else ds_id[:5]
        prefixes.setdefault(prefix, []).append(ds_id)

    for prefix in sorted(prefixes.keys()):
        ids = prefixes[prefix]
        print(f"  {prefix}: {len(ids)} datasets")
        if len(ids) <= 3:
            for ds_id in ids:
                print(f"    {ds_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Build mission catalog from CDAWeb REST API"
    )
    parser.add_argument(
        "--mission", type=str,
        help="Build only this mission (e.g., psp, ace). Case-insensitive.",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Show CDAWeb datasets not matching any known mission.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Fetch the full catalog
    catalog = fetch_cdaweb_catalog()
    if not catalog:
        print("Error: Could not fetch CDAWeb catalog.")
        sys.exit(1)

    if args.discover:
        discover_unmatched(catalog)
        return

    if args.mission:
        # Build a single mission
        stem = args.mission.lower()
        mission = build_mission_json(stem, catalog)
        save_mission_json(stem, mission)
    else:
        # Build all missions found in the catalog
        discovered_stems: set[str] = set()
        for ds_id in catalog:
            mission_stem, _ = match_dataset_to_mission(ds_id)
            if mission_stem:
                discovered_stems.add(mission_stem)

        print(f"\nBuilding {len(discovered_stems)} missions...")
        for stem in sorted(discovered_stems):
            mission = build_mission_json(stem, catalog)
            save_mission_json(stem, mission)

    print("\nDone!")


if __name__ == "__main__":
    main()
