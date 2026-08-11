"use client";
import { useState } from "react";
import { Observation, TelemetryPoint } from "../types/analysis";
const observations: Observation[] = [
  {
    id: "OBS-01",
    timestamp: "00:03:42.800",
    description:
      "A vehicle in the right lane begins moving toward the ego vehicle's lane.",
    evidence: "Frames F08–F10",
  },
  {
    id: "OBS-02",
    timestamp: "00:03:44.100",
    description:
      "The relative distance between the ego vehicle and the nearby vehicle decreases.",
    evidence: "Frames F10–F12",
  },
  {
    id: "OBS-03",
    timestamp: "00:03:45.400",
    description: "The ego vehicle appears to begin slowing.",
    evidence: "Frames F12–F14",
  },
];
const telemetry: TelemetryPoint[] = [
  { timestamp: "00:03:42.0", speed: 36, brake: "0%", steering: "1.2°" },
  { timestamp: "00:03:44.0", speed: 31, brake: "18%", steering: "2.0°" },
  {
    timestamp: "00:03:45.2",
    speed: 27,
    brake: "44%",
    steering: "2.5°",
    recorded: true,
  },
  { timestamp: "00:03:46.0", speed: 24, brake: "61%", steering: "2.7°" },
];
type Props = { onSeek: (timestamp: string) => void };

export function EvidenceDetails({ onSeek }: Props) {
  const [selected, setSelected] = useState("F12");
  const [selectedObservation, setSelectedObservation] = useState("");
  return (
    <>
      <section className="processing-panel observations-panel">
        <div className="panel-heading">
          <p className="eyebrow">Visual observations</p>
          <h2>Preliminary observations</h2>
          <p>Preliminary observations grounded in the current video window.</p>
        </div>
        <div className="observation-list">
          {observations.map((item) => (
            <button
              type="button"
              className={`observation ${selectedObservation === item.id ? "selected" : ""}`}
              key={item.id}
              onClick={() => {
                setSelectedObservation(item.id);
                onSeek(item.timestamp);
              }}
              aria-label={`Play video at ${item.timestamp} for ${item.id}`}
            >
              <div className="observation-key">
                <strong>{item.id}</strong>
                <span>{item.timestamp}</span>
              </div>
              <p>{item.description}</p>
              <small>
                Evidence: <b>{item.evidence}</b>
              </small>
            </button>
          ))}
        </div>
      </section>
      <section className="processing-panel frames-panel">
        <div className="panel-heading">
          <p className="eyebrow">Visual evidence</p>
          <h2>Referenced frames</h2>
        </div>
        <div className="frame-grid">
          {[
            { id: "F08", time: "00:03:42.800", observation: "OBS-01" },
            { id: "F10", time: "00:03:44.100", observation: "OBS-02" },
            { id: "F12", time: "00:03:45.400", observation: "OBS-03" },
          ].map((frame, index) => (
            <button
              type="button"
              key={frame.id}
              className={`frame-card ${selected === frame.id ? "selected" : ""}`}
              onClick={() => setSelected(frame.id)}
            >
              <span className={`frame-image frame-${index + 1}`}>
                <i />
              </span>
              <strong>{frame.id}</strong>
              <small>
                {frame.time} · {frame.observation}
              </small>
            </button>
          ))}
        </div>
      </section>
      <section className="processing-panel telemetry-panel">
        <div className="panel-heading">
          <p className="eyebrow">Telemetry evidence</p>
          <h2>Vehicle state around event</h2>
          <p>
            Evidence synchronized with the recorded disengagement timestamp.
          </p>
        </div>
        <div className="metric-row">
          <div>
            <span>Speed</span>
            <strong>
              36 <i>km/h</i> <em>→</em> 24 <i>km/h</i>
            </strong>
          </div>
          <div>
            <span>Brake</span>
            <strong>
              0% <em>→</em> 61%
            </strong>
          </div>
          <div>
            <span>Steering</span>
            <strong>
              1.2° <em>→</em> 2.7°
            </strong>
          </div>
        </div>
        <div className="telemetry-table">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Speed</th>
                <th>Brake</th>
                <th>Steering</th>
              </tr>
            </thead>
            <tbody>
              {telemetry.map((row) => (
                <tr
                  className={row.recorded ? "recorded-row" : ""}
                  key={row.timestamp}
                >
                  <td>
                    {row.timestamp}
                    {row.recorded && <small> Recorded</small>}
                  </td>
                  <td>{row.speed} km/h</td>
                  <td>{row.brake}</td>
                  <td>{row.steering}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
