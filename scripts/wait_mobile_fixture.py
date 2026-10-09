#!/usr/bin/env python3
"""Wait for our isolated local fixture, with useful startup failure diagnostics."""
import argparse
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5059")
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    origin = urlsplit(args.base_url)
    if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost", "::1"} or origin.path not in {"", "/"} or origin.query or origin.fragment or origin.username or origin.password:
        parser.error("fixture readiness requires a loopback HTTP origin")
    if args.pid <= 0 or args.timeout <= 0:
        parser.error("PID and timeout must be positive")
    opener = build_opener(ProxyHandler({}))  # Never send localhost through a runner proxy.
    deadline = time.monotonic() + args.timeout
    failure = "no response"
    while time.monotonic() < deadline:
        try:
            os.kill(args.pid, 0)
        except ProcessLookupError:
            raise SystemExit("The isolated fixture process exited before readiness. See its startup log.")
        try:
            with opener.open(args.base_url.rstrip("/") + "/healthz", timeout=min(1, max(0.01, deadline - time.monotonic()))) as response:
                payload = json.load(response)
                if response.headers.get("X-PartyMail-Fixture") == "isolated" and payload.get("status") == "ok":
                    print("Isolated Party Mail fixture is ready.")
                    return 0
                failure = "the port is serving another service, not the isolated Party Mail fixture"
        except HTTPError as error:
            failure = f"HTTP {error.code}"
        except (URLError, OSError, ValueError):
            failure = "connection refused or unreadable response"
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise SystemExit(f"Isolated fixture did not become ready within {args.timeout:g}s ({failure}). See its startup log.")


if __name__ == "__main__":
    raise SystemExit(main())
