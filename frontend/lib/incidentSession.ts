export const INCIDENT_KEYS = {
  timestamp: "vlens:event-timestamp",
  incidentId: "vlens:incident-id",
  reviewMetrics: "vlens:review-metrics",
} as const;

export function isTimestamp(value: string) {
  const match = /^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/.exec(value);
  return Boolean(
    match &&
      Number(match[1]) <= 23 &&
      Number(match[2]) <= 59 &&
      Number(match[3]) <= 59,
  );
}

export function timestampToSeconds(value: string) {
  const parts = value.split(":").map(Number);
  if (parts.length === 3 && parts.every(Number.isFinite)) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  if (parts.length === 2 && parts.every(Number.isFinite)) {
    return parts[0] * 60 + parts[1];
  }
  return 0;
}

export function secondsToTimestamp(value: number) {
  const safe = Math.max(0, value);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = Math.floor(safe % 60);
  const milliseconds = Math.round((safe - Math.floor(safe)) * 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}

export function getAnalysisWindow(timestamp: string, radius = 10) {
  const center = timestampToSeconds(timestamp);
  return {
    start: secondsToTimestamp(center - radius),
    end: secondsToTimestamp(center + radius),
  };
}
