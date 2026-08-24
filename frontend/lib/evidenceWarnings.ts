const decimalVi = (value: string) => value.replace(".", ",");

export function formatEvidenceWarning(warning: string): string {
  const extremeAcceleration = warning.match(
    /^LOG_EXTREME_ACCELERATION at ([\d.]+)s: adaptive change \(peak z-score ([\d.]+)\) merged from ([\d.]+)s to ([\d.]+)s$/,
  );
  if (extremeAcceleration) {
    const [, detectedAt, peakZScore, start, end] = extremeAcceleration;
    return `Telemetry ghi nhận biến đổi gia tốc bất thường tại ${decimalVi(detectedAt)} giây (z-score cực đại ${decimalVi(peakZScore)}), trong khoảng ${decimalVi(start)}–${decimalVi(end)} giây.`;
  }

  const contradictedClaim = warning.match(/^Unresolved contradicted claim:\s*(.+)$/i);
  if (contradictedClaim) {
    return `Nhận định mâu thuẫn chưa được xử lý: ${contradictedClaim[1]}. Cần kỹ sư kiểm tra lại bằng chứng video và telemetry.`;
  }

  return warning;
}
