"use client";

import { ChangeEvent, DragEvent, useRef, useState } from "react";

type Props = { kind: "video" | "telemetry"; file: File | null; onChange: (file: File | null) => void };

const formatBytes = (bytes: number) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function FileUploadCard({ kind, file, onChange }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const isVideo = kind === "video";
  const label = isVideo ? "Driving Video" : "Vehicle Telemetry";
  const accept = isVideo ? ".mp4,video/mp4" : ".csv,text/csv";
  const validate = (candidate?: File) => {
    if (!candidate) return;
    const correctType = isVideo ? candidate.name.toLowerCase().endsWith(".mp4") : candidate.name.toLowerCase().endsWith(".csv");
    if (!correctType) { setError(`${label} must be a ${isVideo ? "MP4" : "CSV"} file.`); onChange(null); return; }
    setError(""); onChange(candidate);
  };
  const selectFile = (event: ChangeEvent<HTMLInputElement>) => validate(event.target.files?.[0]);
  const drop = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); setDragging(false); validate(event.dataTransfer.files[0]); };
  return <section className={`upload-card ${file ? "selected" : ""} ${error ? "invalid" : ""}`}>
    <div className="card-heading"><span className="file-icon">{isVideo ? "▶" : "▤"}</span><div><h2>{label}</h2><p>{isVideo ? "Upload the recorded driving video associated with the disengagement." : "Upload timestamped vehicle telemetry from the same driving session."}</p></div><span className="format-badge">{isVideo ? "MP4 only" : "CSV only"}</span></div>
    {file ? <div className="selected-file"><span className="file-check">✓</span><div><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></div><button type="button" onClick={() => { onChange(null); setError(""); if (input.current) input.current.value = ""; }}>Remove</button></div> : <div className={`dropzone ${dragging ? "dragging" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop} onClick={() => input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}><span className="upload-arrow">↑</span><span>Drag and drop or <b>click to browse</b></span><input ref={input} type="file" accept={accept} onChange={selectFile} aria-label={`Choose ${label}`} /></div>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}
