"use client";

import { ChangeEvent, DragEvent, useRef, useState } from "react";

type Props = {
  kind: "video" | "telemetry";
  files: File[];
  onChange: (files: File[]) => void;
};

const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
const telemetryExtensions = [".csv", ".txt", ".json", ".xls", ".xlsx"];

export function FileUploadCard({ kind, files, onChange }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const isVideo = kind === "video";
  const label = isVideo ? "Driving Video" : "Vehicle Telemetry";
  const accept = isVideo
    ? ".mp4,video/mp4"
    : ".csv,.txt,.json,.xls,.xlsx,text/csv,text/plain,application/json,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const validate = (candidates: File[]) => {
    if (!candidates.length) return;
    const validFiles = candidates.filter((candidate) => {
      const fileName = candidate.name.toLowerCase();
      return isVideo
        ? fileName.endsWith(".mp4")
        : telemetryExtensions.some((extension) => fileName.endsWith(extension));
    });
    if (validFiles.length !== candidates.length) {
      setError(
        `${label} accepts ${isVideo ? "MP4" : "CSV, TXT, JSON, XLS, and XLSX"} files only.`,
      );
    } else {
      setError("");
    }
    if (!validFiles.length) return;
    if (isVideo) {
      onChange([validFiles[0]]);
      return;
    }
    const combined = [...files, ...validFiles];
    onChange(
      combined.filter(
        (file, index) =>
          combined.findIndex(
            (item) =>
              item.name === file.name &&
              item.size === file.size &&
              item.lastModified === file.lastModified,
          ) === index,
      ),
    );
  };
  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    validate(Array.from(event.target.files ?? []));
    event.target.value = "";
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    validate(Array.from(event.dataTransfer.files));
  };
  return (
    <section
      className={`upload-card ${files.length ? "selected" : ""} ${error ? "invalid" : ""}`}
    >
      <div className="card-heading">
        <span className="file-icon">{isVideo ? "▶" : "▤"}</span>
        <div>
          <h2>{label}</h2>
          <p>
            {isVideo
              ? "Upload the recorded driving video associated with the disengagement."
              : "Upload timestamped vehicle telemetry from the same driving session."}
          </p>
        </div>
        <span className="format-badge">
          {isVideo ? "MP4 only" : "CSV · TXT · JSON · Excel"}
        </span>
      </div>
      {files.length ? (
        <div className="selected-files">
          {files.map((file) => (
            <div className="selected-file" key={`${file.name}-${file.size}-${file.lastModified}`}>
              <span className="file-check">✓</span>
              <div>
                <strong>{file.name}</strong>
                <small>{formatBytes(file.size)}</small>
              </div>
              <button
                type="button"
                onClick={() => {
                  onChange(files.filter((item) => item !== file));
                  setError("");
                }}
              >
                Remove
              </button>
            </div>
          ))}
          {!isVideo && <button className="add-more-files" type="button" onClick={() => input.current?.click()}>+ Add more files</button>}
          <input ref={input} type="file" hidden multiple accept={accept} onChange={selectFile} aria-label={`Add more ${label} files`} />
        </div>
      ) : (
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
          onClick={() => input.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
        >
          <span className="upload-arrow">↑</span>
          <span>
            Drag and drop or <b>click to browse</b>
          </span>
          <input
            ref={input}
            type="file"
            multiple={!isVideo}
            accept={accept}
            onChange={selectFile}
            aria-label={`Choose ${label}`}
          />
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
