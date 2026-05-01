import { notFound } from 'next/navigation';

import CustomSourceWizard from './CustomSourceWizard';

export default function CustomSourceConnectPage() {
  if (process.env.NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION !== 'true') {
    notFound();
  }
  return <CustomSourceWizard />;
}
