"""Party Mail TestFlight configuration; no sibling app configuration is loaded."""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_DIR.parents[1]


def _load_dotenv(path: Path) -> None:
    if "pytest" in sys.modules or os.environ.get("PARTYMAIL_DEPLOY_NO_ENV") == "1":
        return
    if path.is_file():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(DEPLOY_DIR / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


PROJECT = _env("TF_PROJECT", str(REPO_ROOT / "ios" / "PartyMail.xcodeproj"))
SCHEME = _env("TF_SCHEME", "PartyMail")
APP_NAME = _env("TF_APP_NAME", "PartyMail")
BUNDLE_ID = _env("TF_BUNDLE_ID", "com.davidfwatson.partymail")
APP_ENTITLEMENTS = _env("TF_APP_ENTITLEMENTS", str(REPO_ROOT / "ios" / "PartyMail" / "PartyMail.entitlements"))
TEAM_ID = _env("TF_TEAM_ID", "2FZS79QCFD")
DIST_IDENTITY = _env("TF_DIST_IDENTITY", f"Apple Distribution: David Watson ({TEAM_ID})")
# Party Mail has no widget extension. Optional extension declarations are explicit.
REQUIRED_EXTENSION_IDS = tuple(v.strip() for v in os.environ.get("TF_REQUIRED_EXTENSION_IDS", "").split(",") if v.strip())
UNSIGNED_EXTENSION_ENTITLEMENTS = dict(entry.strip().split("=", 1) for entry in os.environ.get("TF_UNSIGNED_EXTENSION_ENTITLEMENTS", "").split(",") if entry.strip())
ASC_KEY_ID = _env("ASC_KEY_ID", "572KA8836R")
ASC_ISSUER_ID = _env("ASC_ISSUER_ID", "69a6de71-90ce-47e3-e053-5b8c7c11a4d1")


def asc_key_path() -> Path:
    explicit = _env("ASC_KEY_PATH")
    return Path(explicit).expanduser() if explicit else Path.home() / "private_keys" / f"AuthKey_{ASC_KEY_ID}.p8"


def validate_target() -> None:
    if BUNDLE_ID != "com.davidfwatson.partymail" or SCHEME != "PartyMail" or APP_NAME != "PartyMail":
        raise ValueError("Party Mail deploy refuses another app target. Clear unrelated TF_* overrides.")
