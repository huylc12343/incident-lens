"use client";

import { FormEvent, type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { demoAccount, readSession, saveDemoSession } from "../../lib/auth";
import styles from "./login.module.css";

type IconName = "mail" | "lock" | "eye" | "eyeOff" | "arrow";

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>,
    lock: <><rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></>,
    eyeOff: <><path d="m3 3 18 18" /><path d="M10.6 6.2A10.9 10.9 0 0 1 12 6c6.5 0 10 6 10 6a18.2 18.2 0 0 1-3.1 3.7M6.2 6.3C3.5 8.1 2 12 2 12s3.5 6 10 6c1.2 0 2.3-.2 3.3-.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
  };

  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function GoogleIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.5a4.7 4.7 0 0 1-2 3.1v2.5h3.2c1.9-1.8 3.1-4.3 3.1-7.4Z" /><path fill="#34A853" d="M12 22c2.7 0 5-.9 6.7-2.4l-3.2-2.5c-.9.6-2 .9-3.5.9-2.7 0-5-1.8-5.8-4.3H2.9v2.6A10 10 0 0 0 12 22Z" /><path fill="#FBBC05" d="M6.2 13.7a6 6 0 0 1 0-3.5V7.6H2.9a10 10 0 0 0 0 8.8l3.3-2.7Z" /><path fill="#EA4335" d="M12 6.1c1.5 0 2.9.5 4 1.6l3-3A10 10 0 0 0 2.9 7.6l3.3 2.6C7 7.9 9.3 6.1 12 6.1Z" /></svg>;
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [credentialsError, setCredentialsError] = useState("");
  const router = useRouter();

  const emailError = submitted && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? "Vui lòng nhập email công việc hợp lệ." : "";
  const passwordError = submitted && !password ? "Vui lòng nhập mật khẩu." : "";

  useEffect(() => {
    if (readSession()) router.replace("/");
  }, [router]);

  function useDemoAccount() {
    setEmail(demoAccount.email);
    setPassword(demoAccount.password);
    setCredentialsError("");
    setSubmitted(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !password) return;
    if (email.trim().toLowerCase() !== demoAccount.email || password !== demoAccount.password) {
      setCredentialsError("Email hoặc mật khẩu không đúng.");
      return;
    }
    setCredentialsError("");
    setLoading(true);
    window.setTimeout(() => {
      saveDemoSession();
      router.replace("/");
    }, 650);
  }

  return (
    <main className={styles.page}>
      <section className={styles.shell} aria-label="Đăng nhập Incident Lens">
        <aside className={styles.showcase}>
          <div className={styles.brand}><span className={styles.brandMark}>IL</span><span>Incident Lens</span></div>
          <div className={styles.heroCopy}>
            <p className={styles.kicker}>EVIDENCE INTELLIGENCE</p>
            <h1>Review incidents with<br />evidence, not assumptions.</h1>
            <p>Hệ thống AI tiên tiến giúp kỹ sư QA và AI phân tích sự cố từ video và dữ liệu telemetry xe một cách chính xác.</p>
          </div>
          <div className={styles.evidencePanel} aria-label="VLens incident detected" role="img" />
          <div className={styles.signal}><span />AI-assisted evidence chain verified</div>
        </aside>

        <div className={styles.formSide}>
          <form className={styles.card} onSubmit={handleSubmit} noValidate>
            <div className={styles.formIntro}><div className={styles.mobileMark}>IL</div><h2>Đăng nhập</h2><p>Truy cập không gian làm việc Incident Lens của bạn.</p></div>
            <label htmlFor="email">Email công việc</label>
            <div className={`${styles.inputWrap} ${emailError ? styles.invalid : ""}`}><Icon name="mail" /><input id="email" type="email" autoComplete="email" placeholder="ten.ho@congty.com" value={email} onChange={(e) => { setEmail(e.target.value); setCredentialsError(""); }} aria-invalid={!!emailError} /></div>
            {emailError && <p className={styles.error}>{emailError}</p>}
            <label htmlFor="password">Mật khẩu</label>
            <div className={`${styles.inputWrap} ${passwordError ? styles.invalid : ""}`}><Icon name="lock" /><input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" placeholder="Nhập mật khẩu" value={password} onChange={(e) => { setPassword(e.target.value); setCredentialsError(""); }} aria-invalid={!!passwordError} /><button type="button" className={styles.eyeButton} onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}><Icon name={showPassword ? "eyeOff" : "eye"} /></button></div>
            {passwordError && <p className={styles.error}>{passwordError}</p>}
            <div className={styles.options}><label className={styles.remember}><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> <span>Ghi nhớ đăng nhập</span></label><a href="#quen-mat-khau">Quên mật khẩu?</a></div>
            {credentialsError && <p className={styles.credentialsError} role="alert">{credentialsError}</p>}
            <button className={styles.submit} type="submit" disabled={loading}>{loading ? <><span className={styles.spinner} />Đang đăng nhập...</> : <>Đăng nhập <Icon name="arrow" /></>}</button>
            <button className={styles.demoButton} type="button" onClick={useDemoAccount}>Dùng tài khoản demo</button>
            <p className={styles.demoHint}>Tài khoản thử nghiệm: user@incidentlens.demo</p>
            <div className={styles.divider}><span>hoặc</span></div>
            <button className={styles.google} type="button"><GoogleIcon />Tiếp tục với Google</button>
            <p className={styles.footer}>Chưa có tài khoản? <a href="mailto:admin@example.com">Liên hệ quản trị viên</a></p>
          </form>
        </div>
      </section>
    </main>
  );
}
