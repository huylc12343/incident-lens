"use client";

import Image from "next/image";
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
            <h1 id="page-title">{text("Review driving evidence with confidence.", "Rà soát bằng chứng hành trình một cách tin cậy.")}</h1>
            <p className="hero-copy">
              {text("Analyze synchronized video and telemetry, inspect every AI observation, and keep the engineer in control of the final decision.", "Phân tích video và dữ liệu telemetry đồng bộ, kiểm tra từng quan sát AI và đảm bảo kỹ sư kiểm soát quyết định cuối cùng.")}
            </p>
            <div className="hero-ai-status" aria-label="AI đang sẵn sàng lắng nghe">
              <Image className="hero-ai-mascot" src="/image/ai_pixel.png" alt="Trợ lý AI đang chờ lệnh" width={112} height={112} priority />
              <span className="hero-ai-dots" aria-hidden="true"><i /><i /><i /></span>
              <p>AI đang sẵn sàng lắng nghe</p>
            </div>
          </div>
        </section>
        <AnalysisForm />
        <RecentReviewsTable />
      </main>
    </>
  );
}
