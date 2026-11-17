"""Saved swap spread calibration.

The calibration lives in data/calibration.json inside the GitHub repository.
Saving from the app commits a new version of that file, so every visitor sees
the same numbers and the commit history is a log of every calibration.
"""
import base64
import json
from pathlib import Path

import requests

CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "data" / "calibration.json"
REPO_PATH = "data/calibration.json"
PLACEHOLDER = {"as_of": "placeholder, not calibrated",
               "spreads_bp": {"2": -20.0, "5": -30.0, "10": -45.0}}


def load_calibration():
    """Read the saved spreads (bp) and their date; fall back to placeholders."""
    try:
        saved = json.loads(CALIBRATION_FILE.read_text())
        spreads = {t: float(saved["spreads_bp"][t]) for t in ("2", "5", "10")}
        return {"as_of": str(saved["as_of"]), "spreads_bp": spreads}
    except Exception:
        return PLACEHOLDER


def save_calibration(token, repo, calibration, branch="main"):
    """Commit the calibration file to GitHub. Returns (ok, message)."""
    url = f"https://api.github.com/repos/{repo}/contents/{REPO_PATH}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        body = {
            "message": f"Calibrate swap spreads as of {calibration['as_of']}",
            "content": base64.b64encode(json.dumps(calibration, indent=2).encode()).decode(),
            "branch": branch,
        }
        current = requests.get(url, headers=headers, params={"ref": branch}, timeout=15)
        if current.status_code == 200:          # file exists: GitHub needs its version id
            body["sha"] = current.json()["sha"]
        resp = requests.put(url, headers=headers, json=body, timeout=15)
        if resp.status_code in (200, 201):
            return True, "Saved for all visitors. The app refreshes in about a minute."
        return False, f"GitHub refused the save (status {resp.status_code})."
    except Exception:
        return False, "Could not reach GitHub."
