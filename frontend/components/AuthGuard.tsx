"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { readSession } from "../lib/auth";

export function AuthGuard({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    const session = readSession();
    if (session && isLoginPage) {
      router.replace("/");
      return;
    }
    if (!session && !isLoginPage) {
      router.replace("/login");
      return;
    }
    setChecked(true);
  }, [isLoginPage, router]);

  if (!checked) {
    return <div aria-live="polite" aria-label="Đang kiểm tra phiên đăng nhập" style={{ minHeight: "100vh", background: isLoginPage ? "#171b22" : "#fbfbfd" }} />;
  }

  return <>{children}</>;
}
