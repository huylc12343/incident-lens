"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { EvidenceDetails } from "./EvidenceDetails";
import { ProcessingPipeline } from "./ProcessingPipeline";
import { VideoEvidencePlayer } from "./VideoEvidencePlayer";
import { loadUploadedVideo } from "../lib/uploadStorage";

export function ProcessingContent() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [videoName, setVideoName] = useState("front_camera.mp4");
  useEffect(() => {
    setVideoName(
      sessionStorage.getItem("vlens:video-name") ?? "front_camera.mp4",
    );
    let active = true;
    let objectUrl = "";
    loadUploadedVideo()
      .then((file) => {
        if (!active) return;
        if (file) {
          objectUrl = URL.createObjectURL(file);
          setVideoUrl(objectUrl);
        } else {
          setVideoUrl(sessionStorage.getItem("vlens:video-url") ?? "");
        }
      })
      .catch(() => {
        if (active) setVideoUrl(sessionStorage.getItem("vlens:video-url") ?? "");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);
  const seekToTimestamp = (timestamp: string) => {
    const video = videoRef.current;
    if (!video) return;
    const [hours, minutes, seconds] = timestamp.split(":");
    const targetTime = Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds);
    const seek = () => {
      video.currentTime = Number.isFinite(video.duration)
        ? Math.min(targetTime, video.duration)
        : targetTime;
      void video.play().catch(() => undefined);
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) seek();
    else video.addEventListener("loadedmetadata", seek, { once: true });
    video.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  return (
    <>
      <section className="context-bar">
        <div>
          <span>Analyzing video</span>
          <strong>{videoName}</strong>
        </div>
        <div>
          <span>Analysis Window</span>
          <strong>Full uploaded recording</strong>
        </div>
        <p>
          The uploaded video and telemetry are analyzed without requiring a
          manually entered event timestamp.
        </p>
      </section>
      <div className="processing-layout">
        <div className="processing-main">
          <VideoEvidencePlayer
            videoUrl={videoUrl}
            videoName={videoName}
            videoRef={videoRef}
          />
          <EvidenceDetails onSeek={seekToTimestamp} />
        </div>
        <aside className="processing-sidebar">
          <ProcessingPipeline />
          <section className="processing-panel sources-panel">
            <p className="eyebrow">Evidence sources</p>
            <ul>
              <li>
                ✓ <span>Video loaded</span>
              </li>
              <li>
                ✓ <span>Telemetry loaded</span>
              </li>
            </ul>
          </section>
          <Link className="back-home" href="/">
            ← Back to Home
          </Link>
          <button type="button" className="background-button">
            Run in background
          </button>
        </aside>
      </div>
    </>
  );
}
