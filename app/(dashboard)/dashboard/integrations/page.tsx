import { redirect } from 'next/navigation';

// Multiple call sites push to /dashboard/integrations (CustomSourceWizard,
// SetupBanner, pipeline settings, etc.) but the only real entry point is the
// /connect wizard. Redirect rather than 404.
export default function IntegrationsIndex() {
  redirect('/dashboard/integrations/connect');
}
