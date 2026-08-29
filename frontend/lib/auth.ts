export type UserRole = "user" | "admin";

export type DemoSession = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  isAuthenticated: boolean;
};

export const SESSION_STORAGE_KEY = "incident-lens-demo-session";

export const demoAccount = {
  id: "demo-user-001",
  name: "Demo User",
  email: "user@vlens.demo",
  password: "Vlens123",
  role: "user" as const,
};

export function isValidSession(value: unknown): value is DemoSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<DemoSession>;
  return session.id === demoAccount.id
    && session.name === demoAccount.name
    && session.email === demoAccount.email
    && session.role === "user"
    && session.isAuthenticated === true;
}

export function readSession(): DemoSession | null {
  if (typeof window === "undefined") return null;
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(SESSION_STORAGE_KEY) ?? "null");
    return isValidSession(value) ? value : null;
  } catch {
    return null;
  }
}

export function saveDemoSession() {
  const session: DemoSession = {
    id: demoAccount.id,
    name: demoAccount.name,
    email: demoAccount.email,
    role: demoAccount.role,
    isAuthenticated: true,
  };
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearDemoSession() {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}
