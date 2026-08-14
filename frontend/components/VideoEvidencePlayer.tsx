"use client";

import type { RefObject } from "react";

export function VideoEvidencePlayer({ videoUrl, videoName, videoRef }: { videoUrl: string; videoName: string; videoRef: RefObject<HTMLVideoElement | null> }) {
  return (
    <section className="video-panel workspace-video-panel">
      <div className="panel-heading inline-heading"><div><p className="eyebrow">Video evidence</p><h2>Full incident recording</h2></div><span className="video-source">{videoName}</span></div>
      {videoUrl ? <div className="video-placeholder uploaded-video"><video ref={videoRef} key={videoUrl} src={videoUrl} controls preload="metadata" aria-label={`Playback of ${videoName}`} /><div className="window-label">Original recording</div></div> : <div className="video-placeholder"><div className="road-lines" /><div className="video-overlay"><span>Video unavailable</span></div></div>}
    </section>
  );
}
