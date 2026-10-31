# Badge and notification examples

AaFI's built-in cards need no files from this directory. These examples adapt an
existing YAML display-badge system to AaFI's journey and lifecycle information.
They are fragments for a reviewed migration, not a self-contained package.

| File | Purpose and placement |
| --- | --- |
| [flight_itinerary_adapter.jinja](flight_itinerary_adapter.jinja) | Journey selection and presentation data; copy into `/config/custom_templates/` |
| [flight_itinerary_display_adapter.yaml](flight_itinerary_display_adapter.yaml) | Display sensor, eligibility, priority mirror and lifecycle notification examples; merge into the owning package |
| [flight_itinerary_display_badge.yaml](flight_itinerary_display_badge.yaml) | Badge card configuration; adapt in the owning dashboard |

Follow the [package migration checklist](../docs/package-migration.md) before
activation. Replace old definitions of the same IDs; do not load both copies.
Adapt the itinerary sensor ID, shared badge templates/priority system, helpers,
notification service and navigation destination to your installation. Preserve
existing display-before/after values; new installations default to 0.5 hours
before departure and two hours after touchdown.

Keep the existing plane-map sensor and its consumers. The adapter supplies
compatible display/position data; it does not create a replacement map entity.
Tracking and API switching belong to AaFI's options, independently of badge
visibility. Notification delivery remains in user automations.

For ordinary card YAML and its options, use the
[dashboard guide](../docs/dashboard-cards.md). For action fields and entity
configuration, use [configuration and usage](../docs/configuration.md).
