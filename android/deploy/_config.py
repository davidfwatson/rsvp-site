"""Party Mail Play configuration, with a dedicated upload signing key."""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent
ANDROID_DIR = DEPLOY_DIR.parent
REPO_ROOT = ANDROID_DIR.parent


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
# Only an explicitly configured key env file is loaded. Importing deploy tooling
# or running offline tests never reads another project's credentials.
if os.environ.get("PARTYMAIL_UPLOAD_ENV"):
    _load_dotenv(Path(os.environ["PARTYMAIL_UPLOAD_ENV"]).expanduser())


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


PACKAGE_NAME = _env("PLAY_PACKAGE", "com.davidfwatson.partymail")
GRADLE_MODULE = _env("PLAY_GRADLE_MODULE", ":app")
TRACK = _env("PLAY_TRACK", "internal")
AAB_PATH = _env("PLAY_AAB_PATH", str(ANDROID_DIR / "app" / "build" / "outputs" / "bundle" / "release" / "app-release.aab"))
UPLOAD_KEYSTORE = _env("PARTYMAIL_UPLOAD_KEYSTORE")
if UPLOAD_KEYSTORE:
    UPLOAD_KEYSTORE = str(Path(UPLOAD_KEYSTORE).expanduser())
    os.environ["PARTYMAIL_UPLOAD_KEYSTORE"] = UPLOAD_KEYSTORE
UPLOAD_PASSWORD = _env("PARTYMAIL_UPLOAD_PASSWORD")
UPLOAD_ALIAS = _env("PARTYMAIL_UPLOAD_ALIAS", "upload")


def service_account_path() -> Path:
    explicit = _env("PLAY_SERVICE_ACCOUNT_JSON")
    return Path(explicit).expanduser() if explicit else Path.home() / "keys" / "play-service-account.json"


def validate_target() -> None:
    if PACKAGE_NAME != "com.davidfwatson.partymail":
        raise ValueError("Party Mail deploy refuses another package. Clear unrelated PLAY_PACKAGE overrides.")
