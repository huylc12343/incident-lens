import { EvaluationContent } from "../../components/EvaluationContent";
import { Header } from "../../components/Header";

export default function EvaluationPage() {
  return (
    <>
      <Header />
      <main className="page-shell evaluation-shell">
        <div className="processing-title">
          <div><p className="incident-breadcrumb">Incidents <span>›</span> Review outcome</p><h1>Decision evaluation</h1></div>
          <p>Operational metrics for the completed human-in-the-loop workflow.</p>
        </div>
        <EvaluationContent />
      </main>
    </>
  );
}
