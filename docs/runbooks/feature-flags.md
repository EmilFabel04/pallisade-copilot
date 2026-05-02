# Feature Flag Runbook

## SOURCES_CATEGORY

Gates the **Sources** integration category — the Custom Source connector plus
"coming soon" tiles for Salesforce, Shopify, and HubSpot. Adds the SOURCE
PipelineLayer to the pipeline diagram (leftmost), the `/integrations/connect`
category-grouped picker, and the new wizard's discovery + verify flow.

### Where the flag is checked

- **Frontend** (`NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY`):
  - `app/(dashboard)/dashboard/integrations/connect/page.tsx` — connect-page picker
  - `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx` — wizard route
  - `app/(dashboard)/dashboard/pipeline/page.tsx` — SOURCE-layer tiles in the connector catalog
  - All four surfaces (pipeline page, connect page, driver registration, probe scheduler) gate on the flag.
- **Backend** (`FEATURE_SOURCES_CATEGORY`):
  - `scanner/drivers/loader.py` — driver registration
  - `scanner/scheduler/probe_runner.py` — scheduled probe execution

### To enable (pilot rollout)

1. Set both env vars to `true` for the pilot tenant's deployment:
   - `NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY=true` (Next.js process)
   - `FEATURE_SOURCES_CATEGORY=true` (FastAPI process)
2. Restart both processes so the env vars take effect.
3. Verify by visiting `/dashboard/integrations/connect` — Sources category should
   appear leftmost; Custom Source tile should route to the wizard.

### To roll back

Unset both env vars (or set to anything other than `"true"`) and restart both
processes. No DB cleanup needed — `Integration` rows of type `CUSTOM_SOURCE`
remain in the DB but are not surfaced or processed when the flag is off.

### Pilot validation checklist (post-enable)

Spot-check at 24h, 1 week, 2 weeks:

- Number of `Integration` rows with `integration_type = 'CUSTOM_SOURCE'` for the
  pilot tenant.
- Number of `CustomSourceProbeRun` rows in the last 24h per integration (should
  match the configured schedule cadence).
- Any rows in `SourceConnectorWaitlist` (signal of demand for Salesforce / Shopify
  / HubSpot).
- Error-event log for `ProbeError` codes — group by `code` to surface common
  failure modes.

### Default-on graduation

After two weeks of stable pilot use with no critical incidents, change the
deployment-config defaults so both env vars are `true` by default for all
tenants. Commit that change as a small follow-up — keep it isolated so it can
be reverted independently.
