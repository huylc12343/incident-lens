"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim } from "../../types/incident";
import { uiText as text } from "../../lib/ui-copy";

type Props = {
  clipUrl: string;
  start?: number;
  focus?: number;
  end?: number;
  claims: Claim[];
  selectedId: string;
  onSelect: (claim: Claim) => void;
  videoRef: RefObject<HTMLVideoElement | null>;
};

const playerTime = (seconds: number) => {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  const remainder = (safe % 60).toFixed(1).padStart(4, "0");
  return `${String(minutes).padStart(2, "0")}:${remainder}`;
};

export function IncidentClipPlayer({ clipUrl, start, focus, end, claims, selectedId, onSelect, videoRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const clipStart = start ?? 0;
  const expectedDuration = start !== undefined && end !== undefined ? Math.max(0, end - start) : 0;
  const timelineDuration = duration || expectedDuration;
  const progress = timelineDuration > 0 ? Math.min(100, (currentTime / timelineDuration) * 100) : 0;

  const markers = useMemo(() => claims
    .filter((claim) => claim.timestamp_s >= clipStart && (!end || claim.timestamp_s <= end))
    .map((claim) => ({ claim, clipTime: Math.max(0, claim.timestamp_s - clipStart) })), [claims, clipStart, end]);
  const eventClipTime = focus !== undefined ? Math.max(0, focus - clipStart) : undefined;
  const position = (time: number) => timelineDuration > 0 ? Math.max(0, Math.min(100, (time / timelineDuration) * 100)) : 0;

  useEffect(() => {
    setCurrentTime(0);
    setDuration(0);
    setPlaying(false);
  }, [clipUrl]);

  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) await video.play(); else video.pause();
  };

  const seek = (time: number) => {
    if (!videoRef.current) return;
    videoRef.current.currentTime = Math.max(0, Math.min(timelineDuration, time));
  };

  const seekFromTrack = (event: MouseEvent<HTMLDivElement>) => {
    if (!timelineDuration) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    seek(((event.clientX - bounds.left) / bounds.width) * timelineDuration);
  };

  const fullscreen = async () => {
    if (containerRef.current?.requestFullscreen) await containerRef.current.requestFullscreen();
  };

  return (
    <section className="incident-clip-card refined-clip-card" aria-labelledby="incident-clip-title">
      <header className="refined-clip-header">
        <div><p className="eyebrow">{text("Extracted evidence", "Bằng chứng đã trích xuất")}</p><h2 id="incident-clip-title">{text("Incident evidence clip", "Video bằng chứng sự cố")}</h2></div>
        <button type="button" className="clip-fullscreen-button" onClick={fullscreen} aria-label={text("View incident clip fullscreen", "Xem video sự cố toàn màn hình")} title={text("Fullscreen", "Toàn màn hình")}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" /></svg>
        </button>
      </header>

      <div className="clip-player-shell" ref={containerRef}>
        <div className="refined-clip-stage">
          {clipUrl ? (
            <video
              ref={videoRef}
              playsInline
              preload="metadata"
              src={clipUrl}
              aria-label={text("Incident evidence clip", "Video bằng chứng sự cố")}
              onClick={togglePlayback}
              onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
              onDurationChange={(event) => setDuration(event.currentTarget.duration)}
              onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onEnded={() => setPlaying(false)}
            />
          ) : <div className="clip-empty-state"><span className="state-spinner" /><p>{text("Generating evidence clip...", "Đang tạo video bằng chứng...")}</p></div>}
        </div>

        <div className="refined-clip-controls">
          <div className="clip-progress-track" onClick={seekFromTrack} role="slider" tabIndex={0} aria-label={text("Video timeline", "Dòng thời gian video")} aria-valuemin={0} aria-valuemax={timelineDuration} aria-valuenow={currentTime}>
            <span className="clip-progress-fill" style={{ width: `${progress}%` }} />
            {markers.map(({ claim, clipTime }) => <button key={claim.claim_id} type="button" className={`clip-evidence-marker ${claim.claim_id === selectedId ? "selected" : ""}`} style={{ left: `${position(clipTime)}%` }} onClick={(event) => { event.stopPropagation(); onSelect(claim); seek(clipTime); }} aria-label={`Seek to ${claim.claim_id} at ${secondsToTimestamp(claim.timestamp_s)}`} title={`${claim.claim_id} · ${secondsToTimestamp(claim.timestamp_s)}`} />)}
            {eventClipTime !== undefined && <button type="button" className="clip-main-event-marker" style={{ left: `${position(eventClipTime)}%` }} onClick={(event) => { event.stopPropagation(); seek(eventClipTime); }} aria-label={`Seek to detected event at ${secondsToTimestamp(focus ?? 0)}`} title={`Detected event · ${secondsToTimestamp(focus ?? 0)}`} />}
            <i className="clip-playhead" style={{ left: `${progress}%` }} />
          </div>
          <div className="clip-control-row">
            <button type="button" className="clip-play-button" onClick={togglePlayback} disabled={!clipUrl} aria-label={playing ? text("Pause video", "Tạm dừng video") : text("Play video", "Phát video")}>
              {playing ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14" /></svg> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z" /></svg>}
            </button>
            <span className="clip-current-time">{playerTime(currentTime)} <i>/</i> {playerTime(timelineDuration)}</span>
          </div>
        </div>
      </div>

    </section>
  );
}
