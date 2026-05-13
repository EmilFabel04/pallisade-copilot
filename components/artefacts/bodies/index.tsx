import type { ArtefactRow } from '@/types/artefact-row';
import { GenericArtifactBody } from './GenericArtifactBody';
import { PRArtifactBody } from './PRArtifactBody';

export function ArtefactBody({ artefact }: { artefact: ArtefactRow }) {
  switch (artefact.kind) {
    case 'PR_CHANGE':
    case 'DBT_CORE_CHANGE':
    case 'DAG':
    case 'SCHEMA_CHANGE':
      return <PRArtifactBody artefact={artefact} />;
    default:
      return <GenericArtifactBody artefact={artefact} />;
  }
}
