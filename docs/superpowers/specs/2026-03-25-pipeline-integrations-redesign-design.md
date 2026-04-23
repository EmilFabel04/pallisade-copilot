# Pipeline Integrations Page Redesign

## Summary

Redesign the pipeline integrations page to replace preset stack templates with a VCS-first integration guide, remove purple recommendation banners, simplify the checklist into a connected-status display, and change the pipeline sidebar icon to avoid duplication with the dashboard icon.

## Changes

### 1. Sidebar Icon (Sidebar.tsx)
- Replace the Pipeline nav item's 4-square grid SVG with a chain-link SVG
- Dashboard keeps its existing grid icon

### 2. Connected Status Bar (pipeline/page.tsx)
- Replace `CHECKLIST_STEPS` rendering (the numbered setup checklist with Required/Optional labels and "Next step" suggestion) with simple status pills
- Each pill shows a green dot + label if any tool in that category is connected, gray dot otherwise
- Categories: Warehouse, Transform, Orchestration, Version Control, BI, Ingestion, Storage, Alerts
- No "Required"/"Optional" language, no "Next step" suggestion

### 3. VCS Integration Callout (pipeline/page.tsx)
- Remove `STACK_TEMPLATES` array and all template selection logic (`selectedTemplateId` state, template rendering, template highlight logic)
- Replace with a callout banner section in the same position (between status bar and search/filters):
  - Blue-bordered info callout explaining the VCS-first approach
  - Message: connect VCS to give open source tools (dbt, Airflow, Dagster) access to their code repos — acts as universal source for repo path config
  - Three provider cards: GitHub, GitLab, Bitbucket — clicking opens the existing VCS tool config modal
- Only shown when no VCS tool is connected (auto-hides once connected)

### 4. Remove Purple Recommendation Banners (pipeline/page.tsx)
- Remove the `recommendations` useMemo and `dismissedRecommendations` state
- Remove the purple banner rendering block at the bottom of the page
- Remove `recommendedWith`/`recommendedReason` references (keep the fields in types.ts as they may be used elsewhere, just don't render banners)

### 5. Unchanged
- Search + filter bar
- Connector cards by group (collapsible sections)
- NodeConfigModal, IntegrationConfigModal
- All tool definitions and integration definitions in types.ts
