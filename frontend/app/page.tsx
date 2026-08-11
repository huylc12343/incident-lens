import { Header } from "../components/Header";
import { AnalysisForm } from "../components/AnalysisForm";
import { RecentReviewsTable } from "../components/RecentReviewsTable";

export default function Home() {
  return (
    <>
      <Header />
      <main className="page-shell">
        <section className="hero" aria-labelledby="page-title">
          <p className="eyebrow">Review workspace</p>
          <h1 id="page-title">AI-Assisted Disengagement Review</h1>
          <p className="hero-copy">
            Review a recorded disengagement using synchronized video and
            telemetry evidence. AI-generated observations remain subject to
            engineer review.
          </p>
          <div className="flow" aria-label="Review workflow">
            <span>Video + Telemetry + Timestamp</span>
            <i aria-hidden="true">→</i>
            <span>AI Analysis</span>
            <i aria-hidden="true">→</i>
            <span>Engineer Review</span>
          </div>
        </section>
        <AnalysisForm />
        <RecentReviewsTable />
      </main>
    </>
  );
}
