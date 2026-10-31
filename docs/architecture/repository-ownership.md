# Repository ownership and distribution

AaFI (`tjuuljensen/ha-airport-itinerary`) is the authoritative repository for the
integration and both Lovelace cards. It owns implementation, tests, documentation,
configuration metadata and reusable examples. This contract consolidates the
existing source/deployment arrangement; it does not change runtime identities.

## Ownership matrix

| Surface | Authoritative source | Consumer / activation | State and recovery |
| --- | --- | --- | --- |
| Integration and offline airport map | `custom_components/airport_aware_itinerary/` in AaFI | `/config/custom_components/airport_aware_itinerary`; Core restart after install | HA manages itinerary and airport cache storage; back up before downgrade |
| Input and schedule cards | AaFI's integration `www/airport-itinerary.js` | Bundled HTTP module, registered by `frontend.py`; browser reload | Keep custom element names and existing card configuration; restore matching resource URL with rollback |
| Tests, CI and development configuration | AaFI root, `tests/`, `browser-tests/`, `.github/` | Local checks and GitHub Actions | No dependency on a sibling checkout for these checks |
| Generic configuration and badge examples | AaFI `docs/` and `examples/` | User-reviewed adaptation into HA configuration | Examples are not automatically installed or a complete shared badge system |
| Installed badge, notifications, existing map and deployment settings | `HomeAssistantConfig` | Its packages, templates, dashboard and deployment workflow | Preserve entity identities, notification destinations, helper values and local backups |
| Legacy community card file | Copied from AaFI by HomeAssistantConfig's component manifest | `/config/www/community/lovelace-airport-itinerary/airport-itinerary.js` | Compatibility output; retain existing artifact ID and rollback target |
| Former standalone repository | `lovelace-airport-itinerary`, retained transition snapshot | Historical references and recovery only | Do not develop or publish independent card updates there |

## Distribution and deployment

The complete integration directory is the installation artifact. The cards are
plain JavaScript served directly from that directory; there is no separate npm
publication, generated bundle, or Dashboard release. HACS metadata uses the
**Integration** category. Release publication is manual and separate from CI.

For the owner's installation, `HomeAssistantConfig/utils/ha-component-deploy-manifest.json`
already names `../ha-airport-itinerary` as the source repository for both artifacts.
Its deployment launcher handles transport, backup and activation. Triggering that
workflow is a runtime operation; editing or pushing AaFI alone is not deployment.
Credentials and host-specific configuration remain outside AaFI. Acceptance checks
cover Core health, bundled HTTP bytes/resource identity and saved schedules.

The legacy URL is retained only as a compatibility target. Known old Lovelace
resource URLs are migrated by AaFI for storage-managed resources; YAML resource
owners follow the [card guide](../dashboard-cards.md). Do not mirror changes back
to the old source repository as a second maintenance workflow.

## Reconciliation record - 31 October 2026

- AaFI already contains the backend, card source and both test suites. The legacy
  card file and bundled file were byte-identical at reconciliation (card 1.6.7).
- HomeAssistantConfig's component manifest and component register already identify
  AaFI as the source for both artifacts; no deployment path change is needed.
- AaFI's README/configuration/contributor guides now cover the combined product.
  The former repository redirects users here and retains its recovery files.
- The GitHub remote's HEAD is the initial `dfd0637` commit, with no tags at this
  audit. Source readiness in the local working tree is distinct from publication.
- These documentation and repository-policy changes do not deploy code, save
  dashboards, change stored trips or migrate notification/map consumers.

The installation-specific deployment and acceptance history remains in
`HomeAssistantConfig/docs/migrations/airport-itinerary-cutover.md`; deployment
operations are in its `docs/runbooks/ha-component-deployment.md`. The generic
[package checklist](../package-migration.md) does not claim every installation
has completed cutover.

## Retirement and rollback

Retain the former repository and legacy compatibility target while recovery or
unverified external consumers remain. Archival/deletion is a separate decision
after consumer review; this reconciliation does neither. Historical snapshots
are not automatically synchronized to new versions.

Runtime rollback uses the deployment's matched integration/card backup and
storage/resource snapshots, not an arbitrary file from the old repository.
Disable new FR24 control options before restoring legacy controllers. Preserve
itinerary IDs, entity IDs, custom element names, lifecycle evidence and unrelated
tracked flights throughout recovery.
