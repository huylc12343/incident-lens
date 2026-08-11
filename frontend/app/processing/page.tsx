import { Header } from "../../components/Header";
import { ProcessingContent } from "../../components/ProcessingContent";
export default function ProcessingPage() {
  return (
    <>
      <Header processing />
      <main className="page-shell processing-shell">
        <div className="processing-title">
          <div>
            <p className="eyebrow">Disengagement review · evidence analysis</p>
            <h1>Processing recorded evidence</h1>
          </div>
          <p>
            Preparing grounded observations and a structured summary for
            engineer review.
          </p>
        </div>
        <ProcessingContent />
      </main>
    </>
  );
}
