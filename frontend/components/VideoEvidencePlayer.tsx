"use client";

import { RefObject, useState } from "react";
import { secondsToTimestamp } from "../lib/incidentSession";
import type { Claim } from "../types/incident";

type Props = {
  videoUrl: string;
  videoName: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  claims?: Claim[];
  incidentWindow?: { t_start?: number; t0?: number; t_end?: number };
};

export function VideoEvidencePlayer({ videoUrl, videoName, videoRef, claims = [], incidentWindow }: Props) {
  const [selected, setSelected] = useState("");
  const timestamps = claims.map((claim) => claim.timestamp_s);
  const start = incidentWindow?.t_start ?? (timestamps.length ? Math.min(...timestamps) : 0);
  const end = incidentWindow?.t_end ?? (timestamps.length ? Math.max(...timestamps) : start + 1);
  const duration = Math.max(end - start, 0.001);
  const markers = claims.slice(0, 8).map((claim) => ({
    at: `${Math.max(2, Math.min(98, ((claim.timestamp_s - start) / duration) * 100))}%`,
    label: claim.claim_id,
    time: secondsToTimestamp(claim.timestamp_s),
    timestamp: claim.timestamp_s,
  }));

  return (
    <section className="video-panel">
      <div className="panel-heading inline-heading">
        <div><p className="eyebrow">Video evidence</p><h2>Event window playback</h2></div>
        <span className="video-source">{videoName}</span>
      </div>
      {videoUrl ? (
        <div className="video-placeholder uploaded-video">
          <video ref={videoRef} key={videoUrl} src={videoUrl} controls preload="metadata" aria-label={`Playback of ${videoName}`} />
          <div className="window-label">Incident recording</div>
        </div>
      ) : (
        <div className="video-placeholder" aria-label="Driving video placeholder"><div className="road-lines" /><div className="video-overlay"><span>FRONT CAMERA</span></div></div>
      )}
      <div className="scrubber">
        <div className="timeline-line">
          {markers.map((marker) => (
            <button type="button" key={marker.label} className={`timeline-marker ${selected === marker.label ? "chosen recorded" : ""}`} style={{ left: marker.at }}
              onClick={() => { setSelected(marker.label); if (videoRef.current) videoRef.current.currentTime = marker.timestamp; }} aria-label={`${marker.label} at ${marker.time}`}>
              <span>●</span>
            </button>
          ))}
        </div>
        <div className="timeline-ticks"><span>{secondsToTimestamp(start)}</span><b>{markers.find((marker) => marker.label === selected)?.time ?? "Select an observation"}</b><span>{secondsToTimestamp(end)}</span></div>
      </div>
    </section>
  );
}
