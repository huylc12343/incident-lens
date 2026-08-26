"use client";

import Image from "next/image";
import { useState } from "react";
import { artifactUrl } from "../../lib/incidentApi";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { IncidentSnapshot } from "../../types/incident";

function ReportEvidenceImage({ src, fallback, alt }: { src: string; fallback: string; alt: string }) {
  const [fallbackActive, setFallbackActive] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const activeSrc = fallbackActive ? fallback : src;
  if (!activeSrc || unavailable) return <div className="report-evidence-image-unavailable">Ảnh không khả dụng</div>;
  return <Image
    unoptimized
    width={800}
    height={450}
    src={activeSrc}
    alt={alt}
    onError={() => {
      if (!fallbackActive && fallback && fallback !== src) setFallbackActive(true);
      else setUnavailable(true);
    }}
  />;
}

export function IncidentEvidenceGallery({ snapshot }: { snapshot: IncidentSnapshot }) {
  const directory = snapshot.artifact_uris.incident_frames?.replace(/[\\/]+$/, "") ?? "";
  const representative = artifactUrl(snapshot.artifact_uris.representative_frame);
  const seen = new Set<string>();
  const evidence = snapshot.claims.flatMap((claim) => claim.evidence.map((item) => ({ ...item, claim })))
    .filter((item) => !seen.has(item.evidence_id) && Boolean(seen.add(item.evidence_id)))
    .sort((left, right) => left.timestamp_s - right.timestamp_s || left.evidence_id.localeCompare(right.evidence_id))
    .map((item) => {
      const filename = /\.[a-z0-9]+$/i.test(item.evidence_id) ? item.evidence_id : `${item.evidence_id}.jpg`;
      return { ...item, imageUrl: directory ? artifactUrl(`${directory}/${filename}`) : representative };
    });

  if (!evidence.length && !representative) return null;
  return <section className="workspace-panel report-evidence-section" id="incident-evidence" aria-labelledby="incident-evidence-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">Visual evidence</p><h2 id="incident-evidence-title">Bằng chứng sự cố</h2></div><span>{evidence.length || 1} ảnh</span></div>
    <p className="report-evidence-intro">Các ảnh được backend trích xuất và liên kết trực tiếp với nhận định trong báo cáo.</p>
    <div className="report-evidence-grid">
      {evidence.map((item, index) => <figure key={item.evidence_id}>
        <div><ReportEvidenceImage src={item.imageUrl} fallback={representative} alt={`Bằng chứng ${index + 1} liên quan ${item.claim.claim_id}`} /><time>{secondsToTimestamp(item.timestamp_s)}</time></div>
        <figcaption><div><strong>Bằng chứng {index + 1}</strong><span>{item.claim.claim_id}</span></div><p>{item.claim.text}</p></figcaption>
      </figure>)}
      {!evidence.length && representative && <figure>
        <div><ReportEvidenceImage src={representative} fallback="" alt={`Ảnh đại diện sự cố ${snapshot.incident_id}`} /></div>
        <figcaption><div><strong>Ảnh đại diện sự cố</strong></div><p>Backend chưa cung cấp frame liên kết riêng cho các claim.</p></figcaption>
      </figure>}
    </div>
  </section>;
}
