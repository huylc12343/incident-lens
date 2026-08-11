"use client";
import { useState } from "react";
const markers = [
  { at: "36%", label: "OBS-01", time: "00:03:42.800" },
  { at: "45%", label: "OBS-02", time: "00:03:44.100" },
  { at: "55%", label: "DISENGAGEMENT", time: "00:03:45.200" },
];
type Props = { videoUrl: string; videoName: string };
export function VideoEvidencePlayer({ videoUrl, videoName }: Props) {
  const [selected, setSelected] = useState("DISENGAGEMENT");
  return (
    <section className="video-panel">
      <div className="panel-heading inline-heading">
        <div>
          <p className="eyebrow">Video evidence</p>
          <h2>Event window playback</h2>
        </div>
        <span className="video-source">{videoName}</span>
      </div>
      {videoUrl ? (
        <div className="video-placeholder uploaded-video">
          <video
            key={videoUrl}
            src={videoUrl}
            controls
            preload="metadata"
            aria-label={`Playback of ${videoName}`}
          />
          <div className="window-label">Full recording</div>
        </div>
      ) : (
        <div
          className="video-placeholder"
          aria-label="Driving video placeholder"
        >
          <div className="road-lines" />
          <div className="video-overlay">
            <span>FRONT CAMERA</span>
          </div>
        </div>
      )}
      <div className="scrubber">
        <div className="timeline-line">
          {markers.map((marker) => (
            <button
              type="button"
              key={marker.label}
              className={`timeline-marker ${marker.label === "DISENGAGEMENT" ? "recorded" : ""} ${selected === marker.label ? "chosen" : ""}`}
              style={{ left: marker.at }}
              onClick={() => setSelected(marker.label)}
              aria-label={`${marker.label} at ${marker.time}`}
            >
              <span>{marker.label === "DISENGAGEMENT" ? "◆" : "●"}</span>
            </button>
          ))}
        </div>
        <div className="timeline-ticks">
          <span>Window start</span>
          <b>{markers.find((marker) => marker.label === selected)?.time}</b>
          <span>Window end</span>
        </div>
      </div>
    </section>
  );
}
