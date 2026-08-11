import { Review } from "../types/review";
import { StatusBadge } from "./StatusBadge";
const reviews: Review[] = [
  {
    id: "DG-001",
    timestamp: "00:03:45.200",
    date: "Aug 08, 2026",
    status: "Pending Review",
    action: "Review",
  },
  {
    id: "DG-002",
    timestamp: "00:12:17.800",
    date: "Aug 08, 2026",
    status: "Processing",
    action: "View",
  },
  {
    id: "DG-003",
    timestamp: "00:08:22.100",
    date: "Aug 07, 2026",
    status: "Approved",
    action: "View",
  },
];
export function RecentReviewsTable() {
  return (
    <section
      id="recent-reviews"
      className="recent-section"
      aria-labelledby="recent-title"
    >
      <div className="recent-heading">
        <div>
          <p className="eyebrow">Review queue</p>
          <h2 id="recent-title">Recent Disengagement Reviews</h2>
        </div>
        <button type="button" className="text-button">
          View history <span>→</span>
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Event ID</th>
              <th>Event Timestamp</th>
              <th>Date</th>
              <th>Review Status</th>
              <th>
                <span className="sr-only">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((review) => (
              <tr key={review.id}>
                <td>
                  <strong>{review.id}</strong>
                </td>
                <td className="mono">{review.timestamp}</td>
                <td>{review.date}</td>
                <td>
                  <StatusBadge status={review.status} />
                </td>
                <td>
                  <button type="button" className="row-action">
                    {review.action} <span>→</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
