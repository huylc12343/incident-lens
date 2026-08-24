import type { IncidentSnapshot } from "../types/incident";

export type DisplayIncidentClassification = {
  type: string;
  severity: string;
};

const normalize = (value: string) => value
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase();

const containsAny = (text: string, phrases: string[]) => phrases.some((phrase) => text.includes(phrase));

export function classifyIncidentForDisplay(snapshot: IncidentSnapshot | null): DisplayIncidentClassification {
  if (!snapshot) return { type: "Phân tích sự cố", severity: "Chưa xác định" };
  // A queued/running snapshot has no final classification yet. In particular,
  // an empty claims array is expected while evidence frames and the review clip
  // are being generated, so it must not be presented as "no incident".
  if (["queued", "running"].includes(snapshot.status)) {
    return { type: "Đang tạo video bằng chứng…", severity: "Đang phân tích" };
  }

  const source = normalize([snapshot.video_summary, ...snapshot.claims.map((claim) => claim.text)].join(" "));
  const collisionDenied = containsAny(source, [
    "khong co va cham",
    "khong quan sat thay va cham",
    "khong phat hien va cham",
    "khong thay va cham",
  ]);
  const collisionObserved = containsAny(source, ["va cham", "dam vao", "tong vao", "tiep xuc"])
    && !collisionDenied;

  let type = "Sự cố khác";
  if (collisionObserved && containsAny(source, ["nguoi di bo", "nguoi bo hanh"])) type = "Va chạm người đi bộ";
  else if (collisionObserved && containsAny(source, ["xe dap", "nguoi di xe dap"])) type = "Va chạm người đi xe đạp";
  else if (collisionObserved && containsAny(source, ["lan can", "hang rao", "tuong", "cay", "via he", "vat can"])) type = "Va chạm vật cố định";
  else if (collisionObserved) type = "Va chạm phương tiện";
  else if (containsAny(source, ["roi khoi phan duong", "lao ra khoi duong", "lech khoi lan duong"])) type = "Rời khỏi phần đường";
  else if (containsAny(source, ["mat kiem soat", "xoay xe", "lat xe"])) type = "Mất kiểm soát";
  else if (containsAny(source, ["suýt va cham", "suýt tong", "near miss"])) type = "Suýt va chạm";
  else if (containsAny(source, ["un tac", "ket trong dong xe", "ket trong giao thong", "dung do giao thong"])) type = "Dừng do ùn tắc";
  else if (containsAny(source, ["cat ngang", "tat dau", "chen vao lan", "cut-in", "cut in"])) type = "Phương tiện cắt ngang";
  else if (containsAny(source, ["phanh khan cap", "phanh gap", "giam toc manh", "dung dot ngot"])) type = "Phanh khẩn cấp";
  else if (collisionDenied || snapshot.claims.length === 0) type = "Không phát hiện sự cố";

  let severity = "Thấp";
  if (type === "Không phát hiện sự cố") severity = "Không có sự cố";
  else if (containsAny(source, ["tu vong", "chay no", "tham khoc"])) severity = "Nghiêm trọng";
  else if (containsAny(source, ["lat xe", "va cham manh", "mat kiem soat", "hau qua dang ke"])) severity = "Cao";
  else if (collisionObserved) severity = "Trung bình";

  return { type, severity };
}
