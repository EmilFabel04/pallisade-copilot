import type { ArtefactRow } from '@/types/artefact-row';
import { GenericArtifactPreview } from './GenericArtifactPreview';
import { PRArtifactPreview } from './PRArtifactPreview';
import { MonitorArtifactPreview } from './MonitorArtifactPreview';

export function ArtefactPreview({ artefact }: { artefact: ArtefactRow }) {
  switch (artefact.kind) {
    case 'PR_CHANGE':
    case 'DBT_CORE_CHANGE':
    case 'DAG':
    case 'SCHEMA_CHANGE':
      if ((artefact.externalRef as { pr_url?: string } | null)?.pr_url) {
        return <PRArtifactPreview artefact={artefact} />;
      }
      return <GenericArtifactPreview artefact={artefact} />;
    case 'MONITOR':
      return <MonitorArtifactPreview artefact={artefact} />;
    default:
      return <GenericArtifactPreview artefact={artefact} />;
  }
}
