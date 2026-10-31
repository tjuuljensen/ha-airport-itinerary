# Contributing to AaFI

AaFI owns the integration, bundled dashboard cards, tests, reusable examples and
documentation. Make card changes in
`custom_components/airport_aware_itinerary/www/airport-itinerary.js`, not in the
former standalone card repository. See the
[ownership contract](docs/architecture/repository-ownership.md) for deployment
and recovery boundaries.

## Repository layout

| Path | Purpose |
| --- | --- |
| `custom_components/airport_aware_itinerary/` | Installable integration, services, translations, branding and offline data |
| `custom_components/airport_aware_itinerary/www/` | Directly served card JavaScript; no bundler or generated `dist` tree |
| `tests/`, `requirements_test.txt`, `pytest.ini` | Backend and HA integration tests |
| `card.test.cjs`, `browser-tests/`, `playwright.config.cjs` | Node and Chromium card tests |
| `package.json`, `package-lock.json` | Frontend development dependencies and reproducible install |
| `scripts/update_airport_timezones.py` | Maintainer updater for the bundled airport map |
| `examples/` | Reusable YAML/Jinja adapters; installation-specific values remain outside AaFI |
| `docs/` | Configuration, card and tracking guides, migration checklist and architecture |
| `.github/workflows/validate.yml` | Frontend, backend, HACS and hassfest validation; no runtime deployment |

## Text and compatibility

Use English for implementation, comments and technical documentation. Preserve
localized data and external entity/API identifiers. Follow `.gitattributes`:
UTF-8 text with LF endings, including Windows edits; PNG assets are binary.
Inspect `git ls-files --eol` before changing cross-platform files. Do not change
global Git EOL settings or normalize unrelated changes.

Keep entity IDs, service names, stored itinerary IDs and saved timestamps stable.
Storage changes require backward-compatible migration and focused regression
coverage. The Home Assistant test baseline is pinned by
`requirements_test.txt` to HA 2026.2.3 on Python 3.13. The frontend dependency in
that file is the HA test fixture dependency, not the bundled card's npm package.
The HACS minimum is HA 2026.2.3, matching the backend test baseline. Keep the
declared minimum and test coverage aligned when adding newer Core APIs.

## Frontend validation

Use Node 22 (the CI version) and npm. From this repository root, these commands
work in PowerShell on Windows and in a Linux shell:

```text
npm ci
npm test
npx playwright install chromium
npm run test:browser
```

`npm ci` uses the committed lockfile. CI installs Chromium's system dependencies
with `npx playwright install --with-deps chromium` on Ubuntu. The Node and browser
tests read the bundled JavaScript directly; neither needs the old repository or
a live Home Assistant server. Keep package and lockfile changes together.

Browser fixtures exercise form preservation, failed saves, return drafts,
tracking messages and narrow layouts. Test widths include 320, 390 and 490px.
Inspect appearance when styling changes. HA icon rendering and operating-system
date/time pickers still require an installed-dashboard acceptance check.

## Backend validation

Use Python 3.13 on Linux with the required HA dependencies, from the repository
root. These commands create a local test environment and install dependencies:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```

The suite includes timezone/DST resolution, matching and tracking ownership,
fetching sessions, airport refresh, frontend resource registration and badge
adapter templates. CI also runs HACS integration validation and hassfest.

### Windows-hosted checkout

Run Node/browser tests with Windows-native tools. Do not run I/O-heavy Linux tests
against `/mnt/c/...`. If backend tests need WSL, use a disposable directory under
the WSL Linux filesystem, include the relevant uncommitted files, and return only
test results. Do not copy the test tree back over the working checkout.

For example, from a WSL shell, replace the example checkout path below with the
Windows checkout path as seen by WSL. `mktemp` creates a unique directory under
`/tmp`:

```bash
source_repo='/mnt/c/path/to/ha-airport-itinerary'
test_root=$(mktemp -d /tmp/aafi-tests.XXXXXX)
tar -C "$source_repo" --exclude=.git --exclude=node_modules --exclude=.venv \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=test-results \
  --exclude=playwright-report -cf - . | tar -C "$test_root" -xf -
cd "$test_root"
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```

This copies working files, including uncommitted changes; a clone or archive of
HEAD alone would miss them. Inspect the resolved temporary path before removing
the disposable copy. For a checkout already inside WSL, run Linux-native tools
there instead of traversing `\\wsl$` from Windows.

## Bundled airport-data maintenance

Runtime **Refresh airport data** updates HA-managed storage, not installed source
files. Updating the release's bundled dataset is a separate maintainer action.
From this repository root, replace the placeholder with a reviewed full upstream
commit SHA:

```text
python scripts/update_airport_timezones.py --commit <full-40-character-sha>
```

Use `--source-file <airports.json>` with the same SHA for a downloaded source.
The updater shares validation with runtime refresh and regenerates deterministic
timezone, city and coordinate maps. Review the diff, run airport-data tests, and
update provenance/counts in `docs/configuration.md` and `NOTICE.md` together.
Retain the upstream MIT notice under `LICENSES/`.

## Release and deployment checks

1. Review the focused diff and untracked source files. Run the relevant backend,
   Node and browser suites, then `git diff --check`. Check local documentation
   links and confirm all required source/test files will be included.
2. For functional releases, update `manifest.json`'s integration version. When
   the card changes, also update its JavaScript version banner and `CARD_VERSION`
   in `frontend.py`; update versioned resource examples in the card guide. A
   documentation-only change does not need a runtime version bump.
3. Confirm the installable integration directory contains the card, offline
   airport data, translations and branding, with no development dependencies or
   caches. CI must pass backend, frontend, HACS and hassfest jobs.
4. Before publishing, verify the supported Core minimum and update `CHANGELOG.md`.
   Tag and publish only the reviewed source when publication is requested. The
   GitHub Release tag must match the integration version (with a `v` prefix).
   HACS installs the integration directory from that tag; a separate card release
   or ZIP asset is not needed. Verify the public release and tagged source after
   publication. HACS metadata alone is not release evidence.
5. Install/update the entire integration as one artifact. Restart Core and reload
   the browser, verify the served card version, resource registration and preserved
   schedules, and check the intended schedule-only/live behavior.

There is no automated release/deployment job here. For the owner's installation,
use HomeAssistantConfig's existing manifest-driven deployment and rollback
workflow; its manifest sources both integration and compatibility-card artifacts
from AaFI. Host access and private settings stay there. Public CI does not receive
private HA credentials or save dashboards.

Keep a matched integration/card backup plus storage and resource snapshots.
Disable new FR24 controls before a downgrade or return to legacy automation;
never run competing controllers. The [package checklist](docs/package-migration.md)
covers that handoff. Keep installation acceptance and backup IDs in the owning
configuration repository, not in generic user documentation.
