"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Header } from "../components/Header";
import { AnalysisForm } from "../components/AnalysisForm";
import { RecentReviewsTable } from "../components/RecentReviewsTable";
import { uiText as text } from "../lib/ui-copy";

const aiMessages = [
  "Chào kỹ sư, tôi là VLens — trợ lý hỗ trợ rà soát sự cố hành trình.",
  "Tôi sẽ trích xuất các mốc thời gian và bằng chứng cần review.",
  "Hãy tải video của một phiên disengagement để bắt đầu.",
  "Bạn có thể thả video và telemetry vào hai ô bên dưới.",
  "Tôi hỗ trợ tóm tắt diễn biến, không thay thế quyết định của kỹ sư.",
];

export default function Home() {
  const [messageIndex, setMessageIndex] = useState(0);
  const [displayedMessage, setDisplayedMessage] = useState(aiMessages[0]);
  const [isFading, setIsFading] = useState(false);
  const hasShownInitialMessage = useRef(false);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reducedMotion.matches) return;

    const interval = window.setInterval(() => {
      setIsFading(true);
      window.setTimeout(() => {
        setMessageIndex((current) => (current + 1) % aiMessages.length);
        setIsFading(false);
      }, 150);
    }, 4000);

    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reducedMotion.matches) {
      setDisplayedMessage(aiMessages[0]);
      return;
    }
    if (!hasShownInitialMessage.current) {
      hasShownInitialMessage.current = true;
      return;
    }

    const characters = Array.from(aiMessages[messageIndex]);
    let nextCharacter = 1;
    setDisplayedMessage(characters[0] ?? "");
    const typing = window.setInterval(() => {
      setDisplayedMessage(characters.slice(0, nextCharacter).join(""));
      nextCharacter += 1;
      if (nextCharacter > characters.length) window.clearInterval(typing);
    }, 14);

    return () => window.clearInterval(typing);
  }, [messageIndex]);

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
              <p className={`hero-ai-message${isFading ? " is-fading" : ""}`} aria-live="off">{displayedMessage}</p>
            </div>
          </div>
        </section>
        <AnalysisForm />
        <RecentReviewsTable />
      </main>
    </>
  );
}
