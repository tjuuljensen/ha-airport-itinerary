# Repository guidance

## Scope and ownership

AaFI is the source of truth for the integration, bundled Lovelace cards, tests,
documentation and reusable examples. Read `CONTRIBUTING.md` and
`docs/architecture/repository-ownership.md` before changing repository boundaries.
Edit cards under `custom_components/airport_aware_itinerary/www/`; do not maintain
a second implementation in `lovelace-airport-itinerary`.

Keep installation-specific badge/map configuration, private settings and runtime
deployment in the owning HA configuration repository. Do not copy credentials or
live `.storage` data here. Source changes alone do not authorize publication,
deployment, repository archival or deletion.

## Repository language

Use English for technical documentation, implementation, identifiers, script
headers and comments. Preserve meaningful localized data and externally owned
entity/API names. Keep stable service names, entity identities and stored trip
IDs; use backward-compatible migrations for storage changes.

## Cross-platform execution

- Determine whether the checkout is on Windows or inside WSL before testing.
- On a Windows filesystem, use native PowerShell, Git and Node for frontend work.
- Run Linux-only backend tests in a disposable WSL Linux-filesystem copy including
  relevant uncommitted changes, never with I/O-heavy tests against `/mnt/<drive>`.
  Return test results only; verify the resolved temporary path before cleanup.
- For WSL-hosted checkouts, use WSL-native tools instead of traversing `\\wsl$`.
- Read `.gitattributes` and `git ls-files --eol` before changing text. Preserve LF
  policy and unrelated working changes; do not change global EOL settings or
  broadly renormalize the repository.

## Validation and documentation

Follow the test and release guidance in `CONTRIBUTING.md`. Tests read bundled card
source directly. Keep package/lockfile changes together. Run checks appropriate
to the change and `git diff --check`; distinguish source validation from runtime
acceptance. Do not claim public release or compatibility based only on metadata.

Keep the README focused on installation and use. Put detailed configuration in
`docs/`, maintenance in `CONTRIBUTING.md`, and ownership in the architecture guide.
Preserve third-party notices and generated airport-data provenance.
