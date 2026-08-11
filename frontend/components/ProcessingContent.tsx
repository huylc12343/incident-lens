"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { EvidenceDetails } from "./EvidenceDetails";
import { ProcessingPipeline } from "./ProcessingPipeline";
import { VideoEvidencePlayer } from "./VideoEvidencePlayer";
import { loadUploadedVideo } from "../lib/uploadStorage";

export function ProcessingContent() {
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
          setVideoName(file.name);
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
          />
          <EvidenceDetails />
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
