"use client";

import { useState, type RefObject } from "react";

export function VideoEvidencePlayer({ videoUrl, videoName, videoRef }: { videoUrl: string; videoName: string; videoRef: RefObject<HTMLVideoElement | null> }) {
  const [playbackError, setPlaybackError] = useState(false);
  return (
    <section className="workspace-video-panel original-video-card" aria-labelledby="original-video-title">
      <header className="evidence-player-header"><div><span className="camera-live-dot" aria-hidden="true" /><div><p className="eyebrow">Primary source</p><h2 id="original-video-title">Original video recording</h2></div></div><span className="video-file-chip">{videoName}</span></header>
      <div className="forensic-video-stage">
        {videoUrl && !playbackError ? <video ref={videoRef} key={videoUrl} src={videoUrl} controls playsInline preload="metadata" onLoadedMetadata={() => setPlaybackError(false)} onError={() => setPlaybackError(true)} aria-label={`Original incident recording ${videoName}`} /> : <div className="video-empty-state"><span aria-hidden="true">{playbackError ? "!" : "▶"}</span><strong>{playbackError ? "Video could not be decoded" : "Original video unavailable"}</strong><p>{playbackError ? "The normalized artifact is unavailable or the browser cannot decode this recording." : "The recording will appear when its artifact is available."}</p></div>}
        <div className="video-stage-label"><span>ORIGINAL</span><small>Normalized evidence source · browser playback</small></div>
      </div>
      <footer className="evidence-player-footer"><span><i className={`source-health-dot ${playbackError ? "failed" : ""}`} /> {playbackError ? "Playback error" : "Source connected"}</span><span>Timeline synchronized</span><span>Use event markers below to seek</span></footer>
    </section>
  );
}
