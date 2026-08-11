import { Header } from "../../components/Header";
import { ReviewContent } from "../../components/ReviewContent";
export default function ReviewPage() {
  return (
    <>
      <Header />
      <main className="page-shell review-shell">
        <div className="processing-title">
          <div>
            <p className="eyebrow">Engineer workspace</p>
            <h1>Disengagement Review</h1>
          </div>
          <p>
            Review the available evidence and structured summary before making a
            decision.
          </p>
        </div>
        <ReviewContent />
      </main>
    </>
  );
}
