import { redirect } from 'next/navigation';

// "Back to Schedule" CTAs from plan detail pages, dashboard cards, and
// notifications all push to /dashboard/schedule, but plans/watches now live on
// /dashboard/monitors. Redirect rather than 404.
export default function ScheduleIndex() {
  redirect('/dashboard/monitors');
}
