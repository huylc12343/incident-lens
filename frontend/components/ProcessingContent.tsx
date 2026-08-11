"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { EvidenceDetails } from "./EvidenceDetails";
import { ProcessingPipeline } from "./ProcessingPipeline";
import { VideoEvidencePlayer } from "./VideoEvidencePlayer";

export function ProcessingContent() {
  const [videoUrl, setVideoUrl] = useState("");
  const [videoName, setVideoName] = useState("front_camera.mp4");
  const [eventTimestamp, setEventTimestamp] = useState("00:03:45.200");
  useEffect(() => {
    setVideoUrl(sessionStorage.getItem("vlens:video-url") ?? "");
    setVideoName(sessionStorage.getItem("vlens:video-name") ?? "front_camera.mp4");
    setEventTimestamp(sessionStorage.getItem("vlens:event-timestamp") ?? "00:03:45.200");
  }, []);
  return <><section className="context-bar"><div><span>Analyzing video</span><strong>{videoName}</strong></div><div><span>Recorded Disengagement</span><strong>{eventTimestamp}</strong><small>Provided event timestamp</small></div><div><span>Analysis Window</span><strong>Event timestamp <i>→</i> ±10 seconds</strong></div><p>Analysis is limited to the evidence window around the provided disengagement timestamp.</p></section><div className="processing-layout"><div className="processing-main"><VideoEvidencePlayer videoUrl={videoUrl} videoName={videoName} eventTimestamp={eventTimestamp} /><EvidenceDetails /></div><aside className="processing-sidebar"><ProcessingPipeline /><section className="processing-panel sources-panel"><p className="eyebrow">Evidence sources</p><ul><li>✓ <span>Video loaded</span></li><li>✓ <span>Telemetry loaded</span></li><li>✓ <span>Timestamp anchor available</span></li></ul></section><Link className="back-home" href="/">← Back to Home</Link><button type="button" className="background-button">Run in background</button></aside></div></>;
}
