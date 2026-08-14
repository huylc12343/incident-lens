import { Header } from "../components/Header";
import { AnalysisForm } from "../components/AnalysisForm";
import { RecentReviewsTable } from "../components/RecentReviewsTable";

export default function Home() {
  return (
    <>
      <Header />
      <main className="page-shell dashboard-shell">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-content">
            <p className="eyebrow">Forensic incident workspace</p>
            <h1 id="page-title">Review driving evidence with confidence.</h1>
            <p className="hero-copy">
              Analyze synchronized video and telemetry, inspect every AI observation,
              and keep the engineer in control of the final decision.
            </p>
          </div>
          <div className="workflow-card" aria-label="Review workflow">
            <span><b>01</b> Evidence intake</span>
            <i aria-hidden="true">→</i>
            <span><b>02</b> AI analysis</span>
            <i aria-hidden="true">→</i>
            <span><b>03</b> Engineer decision</span>
          </div>
        </section>
        <AnalysisForm />
        <RecentReviewsTable />
      </main>
    </>
  );
}
