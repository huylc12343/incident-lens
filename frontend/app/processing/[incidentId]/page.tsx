import { Header } from "../../../components/Header";
import { IncidentReviewWorkspace } from "../../../components/incident-review/IncidentReviewWorkspace";

export default async function IncidentProcessingPage({ params }: { params: Promise<{ incidentId: string }> }) {
  const { incidentId } = await params;
  return (
    <>
      <Header processing />
      <main className="page-shell incident-review-shell">
        <IncidentReviewWorkspace incidentId={incidentId} />
      </main>
    </>
  );
}
