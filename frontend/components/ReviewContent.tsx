"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

type Status = "Pending Review" | "Approved" | "Rejected";
const initialSummary = `Recorded Event\nDisengagement at 00:06.800\n\nObserved Before Event\n• Vehicle moved toward the lane boundary.\n• Relative lateral position changed before disengagement.\n\nVehicle Response\n• Speed decreased from 42 km/h to 27 km/h.\n• Steering angle increased near the event.\n\nEvidence References\n• Visual: Frames F12–F24\n• Telemetry: speed, steering, brake, lateral acceleration\n\nUnknown / Not Established\n• Root cause is not determined.\n• Driver intent is unknown.\n• No conclusion is made about system fault.`;
const observations = [
  {
    id: "OBS-01",
    time: "00:04.500",
    text: "The vehicle begins moving toward the lane boundary.",
    evidence: "Frames F12–F14",
  },
  {
    id: "OBS-02",
    time: "00:06.000",
    text: "The ego vehicle decelerates abruptly.",
    evidence: "Frames F18–F20",
  },
  {
    id: "OBS-03",
    time: "00:07.500",
    text: "The vehicle remains near the lane boundary after the recorded disengagement.",
    evidence: "Frames F22–F24",
  },
];
const telemetry = [
  { time: "00:04.500", values: "Speed: 42 km/h · Steering: +2.1°" },
  { time: "00:06.000", values: "Speed: 27 km/h · Brake: 63%" },
  {
    time: "00:06.800",
    values: "Steering: +15.2° · Lateral acceleration: 0.61g",
    event: true,
  },
  { time: "00:07.500", values: "Speed: 18 km/h" },
];

export function ReviewContent() {
  const [status, setStatus] = useState<Status>("Pending Review");
  const [editing, setEditing] = useState(false);
  const [summary, setSummary] = useState(initialSummary);
  const [draft, setDraft] = useState(initialSummary);
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("Unsupported observation");
  const [note, setNote] = useState("");
  const startedAt = useRef<number>(0);
  useEffect(() => {
    startedAt.current = Date.now();
  }, []);
  const finish = (nextStatus: Status) => {
    const completedAt = Date.now();
    setStatus(nextStatus);
    setDialog(null);
    console.log({
      reviewStartedAt: new Date(startedAt.current).toISOString(),
      reviewCompletedAt: new Date(completedAt).toISOString(),
      reviewDurationMs: completedAt - startedAt.current,
    }); /* TODO: Send review timing to backend for evaluation. TODO: persist audit trail. */
  };
  return (
    <>
      <section className="review-context">
        <div>
          <p>Recorded Disengagement</p>
          <strong>00:06.800</strong>
          <small>Provided event timestamp</small>
        </div>
        <div>
          <p>Review Status</p>
          <span className={`status ${status.toLowerCase().replace(" ", "-")}`}>
            {status}
          </span>
        </div>
        <div>
          <p>Analysis window</p>
          <strong>
            00:00.000 <i>→</i> 00:20.000
          </strong>
        </div>
        <Link href="/processing">← Back to Processing</Link>
      </section>
      <div className="review-layout">
        <div className="review-main">
          <section className="review-card evidence-video">
            <div className="panel-heading inline-heading">
              <div>
                <p className="eyebrow">Video evidence</p>
                <h2>front_camera.mp4</h2>
              </div>
              <span className="video-source">20 second evidence window</span>
            </div>
            <div className="review-video">
              <div className="video-overlay">
                <span>FRONT CAMERA</span>
                <span>00:06.800</span>
              </div>
              <div className="lane-boundary" />
              <button
                type="button"
                className="play-button"
                aria-label="Play evidence video"
              >
                ▶
              </button>
            </div>
            <div className="review-timeline">
              <div className="review-line">
                {[
                  { l: "OBS-01", t: "00:04.500", p: "23%" },
                  { l: "OBS-02", t: "00:06.000", p: "30%" },
                  { l: "EVENT", t: "00:06.800", p: "34%", event: true },
                  { l: "OBS-03", t: "00:07.500", p: "38%" },
                ].map((item) => (
                  <span
                    className={`review-marker ${item.event ? "event" : ""}`}
                    style={{ left: item.p }}
                    key={item.l}
                  >
                    <b>{item.event ? "◆" : "●"}</b>
                    <small>{item.l}</small>
                    <em>{item.t}</em>
                  </span>
                ))}
              </div>
              <div className="review-range">
                <span>00:00.000</span>
                <strong>Recorded Disengagement · 00:06.800</strong>
                <span>00:20.000</span>
              </div>
            </div>
          </section>
          <section className="review-card">
            <div className="panel-heading">
              <p className="eyebrow">Visual observations</p>
              <h2>Grounded observations</h2>
            </div>
            <div className="review-observations">
              {observations.map((obs) => (
                <article key={obs.id}>
                  <div>
                    <strong>{obs.id}</strong>
                    <span>{obs.time}</span>
                  </div>
                  <p>{obs.text}</p>
                  <small>
                    Evidence: <b>{obs.evidence}</b>
                  </small>
                </article>
              ))}
            </div>
          </section>
          <section className="review-card">
            <div className="panel-heading">
              <p className="eyebrow">Telemetry evidence</p>
              <h2>Timestamped vehicle signals</h2>
            </div>
            <div className="signal-list">
              {telemetry.map((signal) => (
                <div
                  className={signal.event ? "event-signal" : ""}
                  key={signal.time}
                >
                  <strong>{signal.time}</strong>
                  <span>{signal.values}</span>
                  {signal.event && <small>Recorded disengagement</small>}
                </div>
              ))}
            </div>
          </section>
        </div>
        <aside className="review-sidebar">
          <section className="review-card summary-card">
            <div className="panel-heading inline-heading">
              <div>
                <p className="eyebrow">Structured summary</p>
                <h2>Evidence summary</h2>
              </div>
              {editing ? <span className="editing-label">Editing</span> : null}
            </div>
            {editing ? (
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                aria-label="Editable structured summary"
              />
            ) : (
              <div className="summary-text">
                {summary.split("\n").map((line, index) =>
                  line ? (
                    <p
                      className={
                        line.includes("Event") ||
                        line.includes("Response") ||
                        line.includes("References") ||
                        line.includes("Established")
                          ? "summary-subtitle"
                          : ""
                      }
                      key={`${line}-${index}`}
                    >
                      {line}
                    </p>
                  ) : (
                    <br key={`break-${index}`} />
                  ),
                )}
              </div>
            )}
            <div className="reference-chips">
              <button type="button">OBS-01</button>
              <button type="button">OBS-02</button>
              <button type="button">TEL-01</button>
            </div>
            {editing ? (
              <div className="edit-actions">
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => {
                    setDraft(summary);
                    setEditing(false);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="approve-action"
                  onClick={() => {
                    setSummary(draft);
                    setEditing(false);
                  }}
                >
                  Save Changes
                </button>
              </div>
            ) : (
              <div className="review-actions">
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => {
                    setDraft(summary);
                    setEditing(true);
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="reject-action"
                  onClick={() => setDialog("reject")}
                  disabled={status !== "Pending Review"}
                >
                  Reject
                </button>
                <button
                  type="button"
                  className="approve-action"
                  onClick={() => setDialog("approve")}
                  disabled={status !== "Pending Review"}
                >
                  Approve
                </button>
              </div>
            )}
          </section>
          <section className="review-card limitations">
            <p className="eyebrow">Evidence limitations</p>
            <ul>
              <li>Root cause is outside the scope of this MVP.</li>
              <li>
                Observations are limited to the uploaded video and telemetry.
              </li>
              <li>Engineer review is required before approval.</li>
            </ul>
          </section>
        </aside>
      </div>
      {dialog && (
        <div className="dialog-backdrop" role="presentation">
          <section
            className="review-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
          >
            <p className="eyebrow">Engineer review</p>
            <h2 id="dialog-title">
              {dialog === "approve"
                ? "Approve this structured summary?"
                : "Reject this structured summary?"}
            </h2>
            {dialog === "approve" ? (
              <p>
                Approval confirms that the engineer has reviewed the available
                evidence.
              </p>
            ) : (
              <>
                <label htmlFor="reject-reason">Reason</label>
                <select
                  id="reject-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                >
                  <option>Unsupported observation</option>
                  <option>Incorrect timestamp</option>
                  <option>Incorrect telemetry interpretation</option>
                  <option>Insufficient evidence</option>
                  <option>Other</option>
                </select>
                <label htmlFor="reject-note">
                  Comment <span>(optional)</span>
                </label>
                <textarea
                  id="reject-note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Add context for this review decision"
                />
              </>
            )}
            <div className="dialog-actions">
              <button
                type="button"
                className="secondary-action"
                onClick={() => setDialog(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={
                  dialog === "approve" ? "approve-action" : "reject-action"
                }
                onClick={() =>
                  finish(dialog === "approve" ? "Approved" : "Rejected")
                }
              >
                {dialog === "approve" ? "Approve Summary" : "Confirm Reject"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
