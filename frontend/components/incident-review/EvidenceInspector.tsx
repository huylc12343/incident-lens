import { artifactUrl } from "../../lib/incidentApi";
import type { Claim, IncidentSnapshot } from "../../types/incident";

export function EvidenceInspector({ snapshot, claim }: { snapshot: IncidentSnapshot; claim?: Claim }) {
  const directory = snapshot.artifact_uris.incident_frames;
  const representative = artifactUrl(snapshot.artifact_uris.representative_frame);
  const evidence = claim?.evidence ?? [];
  return (
    <section className="workspace-panel evidence-inspector">
      <div className="workspace-panel-heading"><div><p className="eyebrow">Selected evidence</p><h2>{claim?.claim_id ?? "Incident evidence"}</h2></div><span>{claim?.verification_status ?? "pending"}</span></div>
      <div className="workspace-evidence-grid">
        {evidence.map((item) => <figure key={item.evidence_id}><img src={directory ? artifactUrl(`${directory}/${item.evidence_id}.jpg`) : representative} alt={`Evidence ${item.evidence_id}`} /><figcaption>{item.evidence_id}</figcaption></figure>)}
        {!evidence.length && representative && <figure><img src={representative} alt="Representative incident evidence" /><figcaption>Representative frame</figcaption></figure>}
        {!evidence.length && !representative && <p>Evidence frames are not available yet.</p>}
      </div>
    </section>
  );
}
