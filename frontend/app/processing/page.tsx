import { Header } from "../../components/Header";
import { IncidentReviewWorkspace } from "../../components/incident-review/IncidentReviewWorkspace";

export default function ProcessingPage() {
  return (
    <>
      <Header processing />
      <main className="page-shell incident-review-shell">
        <IncidentReviewWorkspace />
      </main>
    </>
  );
}
