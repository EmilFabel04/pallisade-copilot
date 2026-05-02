import { notFound } from 'next/navigation';

import CustomSourceWizard from './CustomSourceWizard';

export default function CustomSourceConnectPage() {
  if (process.env.NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY !== 'true') {
    notFound();
  }
  return <CustomSourceWizard />;
}
