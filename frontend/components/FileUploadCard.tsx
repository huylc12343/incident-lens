"use client";

import Image from "next/image";
import { ChangeEvent, DragEvent, useRef, useState } from "react";
import { uiText as text } from "../lib/ui-copy";

type Props = {
  kind: "video" | "telemetry";
  files: File[];
  onChange: (files: File[]) => void;
};

const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
const telemetryExtensions = [".csv"];
const videoIconSrc = "/images/play.png";
const telemetryIconSrc = "/images/waveform.png";

export function FileUploadCard({ kind, files, onChange }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const isVideo = kind === "video";
  const label = isVideo
    ? text("Driving Video", "Video hành trình")
    : text("Vehicle Telemetry (optional)", "Telemetry phương tiện (tùy chọn)");
  const accept = isVideo
    ? ".mp4,video/mp4"
    : ".csv,text/csv";
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
        text(`${label} accepts ${isVideo ? "MP4" : "CSV, TXT, JSON, XLS, and XLSX"} files only.`, `${label} chỉ chấp nhận tệp ${isVideo ? "MP4" : "CSV, TXT, JSON, XLS và XLSX"}.`),
      );
    } else {
      setError("");
    }
    if (!validFiles.length) return;
    if (isVideo) {
      onChange([validFiles[0]]);
      return;
    }
    onChange([validFiles[0]]);
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
        <span className="file-icon">
          <Image src={isVideo ? videoIconSrc : telemetryIconSrc} alt="" width={18} height={18} />
        </span>
        <div>
          <h2>{label}</h2>
          <p>
            {isVideo
              ? text("Upload the recorded driving video associated with the disengagement.", "Tải lên video hành trình liên quan đến sự kiện disengagement.")
              : text("Upload timestamped vehicle telemetry from the same driving session.", "Tải lên telemetry có mốc thời gian từ cùng phiên hành trình.")}
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
                {text("Remove", "Xóa")}
              </button>
            </div>
          ))}
          <button className="add-more-files" type="button" onClick={() => input.current?.click()}>
            {isVideo ? text("Change video", "Đổi video") : text("+ Add more files", "+ Thêm tệp")}
          </button>
          <input ref={input} type="file" hidden accept={accept} onChange={selectFile} aria-label={`Add more ${label} files`} />
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
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              input.current?.click();
            }
          }}
        >
          <span className="upload-arrow">↑</span>
          <span>
            {text("Drag and drop or", "Kéo thả hoặc")} <b>{text("click to browse", "nhấn để chọn tệp")}</b>
          </span>
          <input
            ref={input}
            type="file"
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
