import Image from "next/image";
import { artifactUrl } from "../../lib/incidentApi";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim, IncidentSnapshot } from "../../types/incident";

export function EvidenceInspector({ snapshot, claim }: { snapshot: IncidentSnapshot; claim?: Claim }) {
  const directory = snapshot.artifact_uris.incident_frames;
  const representative = artifactUrl(snapshot.artifact_uris.representative_frame);
  const seen = new Set<string>();
  const evidence = snapshot.claims.flatMap((sourceClaim) => sourceClaim.evidence.map((item) => ({ ...item, claimId: sourceClaim.claim_id, claimText: sourceClaim.text, verification: sourceClaim.verification_status }))).filter((item) => !seen.has(item.evidence_id) && Boolean(seen.add(item.evidence_id)));
  return (
    <section className="workspace-panel evidence-inspector all-evidence-inspector" aria-labelledby="evidence-grid-title">
      <div className="workspace-panel-heading"><div><p className="eyebrow">Visual evidence</p><h2 id="evidence-grid-title">Evidence frame gallery</h2></div><span>{evidence.length || (representative ? 1 : 0)} frame(s)</span></div>
      <p className="evidence-grid-intro">All extracted frames are shown below. The frame linked to the selected timeline event is highlighted.</p>
      <div className="workspace-evidence-grid">
        {evidence.map((item) => <figure className={item.claimId === claim?.claim_id ? "selected" : ""} key={item.evidence_id}><div><Image unoptimized width={640} height={360} src={directory ? artifactUrl(`${directory}/${item.evidence_id}.jpg`) : representative} alt={`${item.evidence_id}: ${item.claimText}`} /><span>{secondsToTimestamp(item.timestamp_s)}</span></div><figcaption><div><strong>{item.evidence_id}</strong><span className={`finding-status ${item.verification}`}>{item.verification.replace("_", " ")}</span></div><p>{item.claimText}</p><small>{item.claimId}</small></figcaption></figure>)}
        {!evidence.length && representative && <figure className="selected"><div><Image unoptimized width={640} height={360} src={representative} alt="Representative incident evidence" /></div><figcaption><div><strong>Representative frame</strong></div><p>{snapshot.video_summary}</p></figcaption></figure>}
        {!evidence.length && !representative && <div className="evidence-grid-empty"><strong>No evidence frames available</strong><p>Frame artifacts will appear after media processing completes.</p></div>}
      </div>
    </section>
  );
}
