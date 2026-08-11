import { EvaluationContent } from "../../components/EvaluationContent";
import { Header } from "../../components/Header";

export default function EvaluationPage() {
  return (
    <>
      <Header />
      <main className="page-shell evaluation-shell">
        <div className="processing-title">
          <div><p className="eyebrow">Evaluation metrics</p><h1>Disengagement Review Evaluation</h1></div>
          <p>Operational metrics for the completed human-in-the-loop review.</p>
        </div>
        <EvaluationContent />
      </main>
    </>
  );
}
