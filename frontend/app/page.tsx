"use client";

import { Header } from "../components/Header";
import { AnalysisForm } from "../components/AnalysisForm";
import { RecentReviewsTable } from "../components/RecentReviewsTable";
import { uiText as text } from "../lib/ui-copy";

export default function Home() {
  return (
    <>
      <Header />
      <main className="page-shell dashboard-shell">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-content">
            <p className="eyebrow">{text("Forensic incident workspace", "Không gian phân tích sự cố")}</p>
            <h1 id="page-title">{text("Review driving evidence with confidence.", "Rà soát bằng chứng hành trình một cách tin cậy.")}</h1>
            <p className="hero-copy">
              {text("Analyze synchronized video and telemetry, inspect every AI observation, and keep the engineer in control of the final decision.", "Phân tích video và dữ liệu telemetry đồng bộ, kiểm tra từng quan sát AI và đảm bảo kỹ sư kiểm soát quyết định cuối cùng.")}
            </p>
          </div>
          <div className="workflow-card" aria-label={text("Review workflow", "Quy trình rà soát")}>
            <span><b>01</b> {text("Evidence intake", "Tiếp nhận bằng chứng")}</span>
            <i aria-hidden="true">→</i>
            <span><b>02</b> {text("AI analysis", "Phân tích AI")}</span>
            <i aria-hidden="true">→</i>
            <span><b>03</b> {text("Engineer decision", "Quyết định của kỹ sư")}</span>
          </div>
        </section>
        <AnalysisForm />
        <RecentReviewsTable />
      </main>
    </>
  );
}
