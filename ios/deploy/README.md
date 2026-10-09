# Party Mail TestFlight

The deployment pipeline is adapted from `../personal-site/ios/deploy`: device
archive, manual distribution re-signing, IPA packaging, `altool` upload, verified
internal TestFlight group attachment, and a build-to-commit provenance ledger.
It targets only `com.davidfwatson.partymail`, scheme/app `PartyMail`, team
`2FZS79QCFD`. There is no widget or inherited DFW Utils extension requirement.

See [the complete mobile release guide](../../docs/mobile-release.md) for first
setup, store metadata, app links, fixtures, CI and optional merge watchers.

```bash
# No signing credentials or store account required:
python3 ios/deploy/testflight.py --preflight --archive-only --skip-upload
python3 ios/deploy/testflight.py --archive-only --skip-upload

# After Party Mail provisioning exists, build an inspectable signed IPA:
python3 ios/deploy/testflight.py --build 1 --skip-upload

# After creating the Party Mail App Store Connect app and internal group:
python3 -m venv ios/deploy/.venv
ios/deploy/.venv/bin/pip install -r ios/deploy/requirements.txt
ios/deploy/.venv/bin/python ios/deploy/testflight.py --auto-build
```

`--build N` updates every `CURRENT_PROJECT_VERSION`; `--set-version 1.0` updates
every `MARKETING_VERSION`. A bare run uses the committed build number. Uploaded
numbers must be unique; `--auto-build` reads ASC first. Commit deliberate build
number changes, and use `[skip ship]` when committing a number already uploaded
by a manual run after enabling the watcher.

`--unsigned-archive` bypasses Xcode account refresh but still requires the Apple
Distribution identity and a Party Mail App Store profile for packaging. Unlike
`--archive-only`, it creates a signed IPA. The packager checks bundle identity,
distribution signatures, profile grants and concrete associated domains.

Configuration comes from local `ios/deploy/.env` and `TF_*`/`ASC_*` overrides;
copy `.env.example`. Keep the `.p8` outside the repository. The API key ID/issuer
can be shared with the existing developer account; the app target cannot.
Provenance defaults to `~/.claude/locks/rsvp-site-build-provenance.tsv`, separate
from personal-site. `TF_PROVENANCE_LOG` overrides that path.

```bash
venv/bin/python -m pytest -q ios/deploy/test_testflight_autoship.py ios/deploy/test_testflight_packaging.py ios/deploy/test_testflight_safety.py
```
