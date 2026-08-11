"use client";

import Link from "next/link";
import { useState } from "react";
import { ReportObservation, ReviewedReport } from "../types/report";
const observations: ReportObservation[] = [
  {
    id: "OBS-01",
    timestamp: "00:04.500",
    observation: "Vehicle moves toward lane boundary",
    source: "Video",
    reference: "Frames F12–F14",
    status: "Accepted",
  },
  {
    id: "OBS-02",
    timestamp: "00:06.000",
    observation: "Vehicle speed decreases",
    source: "Telemetry",
    reference: "Rows 104–112",
    status: "Accepted",
  },
  {
    id: "OBS-03",
    timestamp: "00:06.800",
    observation: "Steering angle increases",
    source: "Telemetry",
    reference: "Rows 113–118",
    status: "Edited",
  },
  {
    id: "OBS-04",
    timestamp: "00:07.500",
    observation: "Vehicle remains near lane boundary",
    source: "Video",
    reference: "Frames F22–F24",
    status: "Accepted",
  },
];
const report: ReviewedReport = {
  reviewId: "VR-001",
  recordedDisengagementTimestamp: "00:06.800",
  reviewStatus: "approved",
  reviewedBy: "Engineer A",
  reviewedAt: "Aug 09, 2026 · 14:20",
  reviewDuration: "2m 06s",
  edited: true,
  observations,
};
const summary = {
  recordedEvent: "Disengagement at 00:06.800",
  observedBeforeEvent: [
    "The vehicle moved toward the lane boundary before the recorded disengagement.",
    "Relative lateral position changed within the analysis window.",
  ],
  vehicleResponse: [
    "Speed decreased from 42 km/h to 27 km/h.",
    "Brake input increased near the event timestamp.",
    "Steering angle changed around the recorded disengagement.",
  ],
  evidenceReferences: [
    "Visual: Frames F12–F24",
    "Telemetry: speed, brake, steering, lateral acceleration",
  ],
  unknowns: [
    "Root cause was not determined.",
    "Driver intent is unknown.",
    "No conclusion is made about system fault.",
  ],
};

export function ReportContent() {
  const [selected, setSelected] = useState("F12");
  const isApproved = report.reviewStatus === "approved";
  const exportJson = () => {
    const payload = {
      reviewId: report.reviewId,
      incidentType: "disengagement",
      recordedDisengagementTimestamp: report.recordedDisengagementTimestamp,
      reviewStatus: report.reviewStatus,
      reviewedBy: report.reviewedBy,
      observations: report.observations.map(
        ({ id, timestamp, observation, reference, status }) => ({
          id,
          timestamp,
          text: observation,
          evidence: reference,
          reviewStatus: status.toLowerCase(),
        }),
      ),
      structuredSummary: summary,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.reviewId}-reviewed-summary.json`;
    link.click();
    URL.revokeObjectURL(
      url,
    ); /* TODO: Export reviewed JSON from the FastAPI report endpoint. */
  };
  return (
    <>
      <section className="report-meta">
        <div>
          <p>Review ID</p>
          <strong>{report.reviewId}</strong>
        </div>
        <div>
          <p>Recorded Disengagement</p>
          <strong>{report.recordedDisengagementTimestamp}</strong>
        </div>
        <div>
          <p>Review Status</p>
          <span className="status approved">Approved</span>
        </div>
        <div>
          <p>Reviewed by</p>
          <strong>{report.reviewedBy}</strong>
        </div>
        <div>
          <p>Reviewed at</p>
          <strong>{report.reviewedAt}</strong>
        </div>
      </section>
      <div className="report-layout">
        <div className="report-main">
          <section className="report-card">
            <div className="panel-heading">
              <p className="eyebrow">Structured summary</p>
              <h2>Engineer-reviewed evidence summary</h2>
            </div>
            <div className="report-summary">
              {Object.entries(summary).map(([key, entries]) => (
                <div key={key}>
                  <h3>
                    {key === "recordedEvent"
                      ? "Recorded Event"
                      : key === "observedBeforeEvent"
                        ? "Observed Before Event"
                        : key === "vehicleResponse"
                          ? "Vehicle Response"
                          : key === "evidenceReferences"
                            ? "Evidence References"
                            : "Unknown / Not Established"}
                  </h3>
                  {Array.isArray(entries) ? (
                    <ul>
                      {entries.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{entries}</p>
                  )}
                </div>
              ))}
            </div>
          </section>
          <section className="report-card">
            <div className="panel-heading">
              <p className="eyebrow">Evidence-backed observations</p>
              <h2>Reviewed observations</h2>
            </div>
            <div className="report-table-wrap">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Observation</th>
                    <th>Evidence Source</th>
                    <th>Evidence Reference</th>
                    <th>Review Status</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.map((item) => (
                    <tr key={item.id}>
                      <td className="mono">{item.timestamp}</td>
                      <td>
                        <strong>{item.observation}</strong>
                        <small>{item.id}</small>
                      </td>
                      <td>{item.source}</td>
                      <td>{item.reference}</td>
                      <td>
                        <span
                          className={`report-status ${item.status.toLowerCase()}`}
                        >
                          {item.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="report-card">
            <div className="panel-heading">
              <p className="eyebrow">Evidence gallery</p>
              <h2>Linked evidence</h2>
            </div>
            <div className="report-gallery">
              {[
                {
                  id: "F12",
                  time: "00:04.500",
                  link: "Supports OBS-01",
                  type: "frame",
                },
                {
                  id: "F18",
                  time: "00:06.000",
                  link: "Supports OBS-02",
                  type: "frame",
                },
                {
                  id: "F22",
                  time: "00:07.500",
                  link: "Supports OBS-04",
                  type: "frame",
                },
                {
                  id: "TEL-01",
                  time: "00:06.000",
                  link: "Speed 42 → 27 km/h",
                  type: "telemetry",
                },
                {
                  id: "TEL-02",
                  time: "00:06.800",
                  link: "Steering +15.2°",
                  type: "telemetry",
                },
              ].map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item.id)}
                  className={`gallery-item ${item.type} ${selected === item.id ? "selected" : ""}`}
                >
                  <span
                    className={
                      item.type === "frame"
                        ? `gallery-frame gallery-frame-${index}`
                        : "telemetry-icon"
                    }
                  >
                    {item.type === "frame" ? "" : "⌁"}
                  </span>
                  <strong>{item.id}</strong>
                  <small>{item.time}</small>
                  <em>{item.link}</em>
                </button>
              ))}
            </div>
          </section>
        </div>
        <aside className="report-sidebar">
          <section className="report-card limitations">
            <p className="eyebrow">Evidence limitations</p>
            <ul>
              <li>Root cause is outside the scope of this MVP.</li>
              <li>
                This summary is limited to the uploaded video and telemetry.
              </li>
              <li>
                Unsupported claims are excluded from the reviewed summary.
              </li>
            </ul>
          </section>
          <section className="report-card audit-card">
            <p className="eyebrow">Review audit</p>
            <dl>
              <div>
                <dt>Status</dt>
                <dd>Approved</dd>
              </div>
              <div>
                <dt>Reviewer</dt>
                <dd>Engineer A</dd>
              </div>
              <div>
                <dt>Edited</dt>
                <dd>Yes</dd>
              </div>
              <div>
                <dt>Review started</dt>
                <dd>14:18:05</dd>
              </div>
              <div>
                <dt>Review completed</dt>
                <dd>14:20:11</dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd>2m 06s</dd>
              </div>
            </dl>
          </section>
          <section className="report-card export-card">
            <p className="eyebrow">Export</p>
            <h2>Reviewed summary</h2>
            <p>Export is available after engineer approval.</p>
            <button
              type="button"
              className="secondary-action"
              disabled={!isApproved}
              onClick={() => console.log("TODO: Generate PDF on backend.")}
            >
              Download PDF
            </button>
            <button
              type="button"
              className="approve-action"
              disabled={!isApproved}
              onClick={exportJson}
            >
              Export JSON
            </button>
          </section>
          <Link className="return-review" href="/review">
            ← Return to Review
          </Link>
        </aside>
      </div>
    </>
  );
}
