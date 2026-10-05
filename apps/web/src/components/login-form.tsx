"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ShieldCheck, Activity, LockKeyhole } from "lucide-react";

// Keep an invitation only in this page's JavaScript memory. Next navigation can
// remount the form after the fragment is removed; no browser storage is used.
let pendingInvitation = "";

export function LoginForm() {
  const [invitation, setInvitation] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const readInvitation = (event?: HashChangeEvent) => {
      // Router hydration can restore the earlier URL before this event runs.
      // The event retains the actual destination fragment in that case.
      const destination = new URL(event?.newURL || location.href);
      const fragment = new URLSearchParams(destination.hash.slice(1)).get(
        "invite",
      );
      const token = fragment || pendingInvitation;
      if (token) {
        pendingInvitation = token;
        queueMicrotask(() => setInvitation(token));
        if (fragment) history.replaceState(history.state, "", "/login");
      }
    };
    readInvitation();
    addEventListener("hashchange", readInvitation);
    queueMicrotask(() => setReady(true));
    return () => removeEventListener("hashchange", readInvitation);
  }, []);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/auth/${invitation ? "accept" : "login"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            password,
            ...(invitation ? { name, token: invitation } : {}),
          }),
        },
      );
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : result.error ||
                "Could not sign in. Check your details and try again.",
        );
      pendingInvitation = "";
      location.assign("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in service unavailable");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-story">
        <a className="auth-brand" href="/login" aria-label="MV Signal sign in">
          <Activity size={30} />
          <span>
            MV<span className="auth-brand-sub"> SIGNAL</span>
          </span>
        </a>
        <div className="auth-story-copy">
          <span className="eyebrow">YOUR MARKET, IN FOCUS</span>
          <h1>
            Every signal.
            <br />A clear reason.
          </h1>
          <p>
            A private workspace for chosen crypto markets. Transparent rules,
            frozen evidence and a complete signal record.
          </p>
          <div className="auth-strategy">
            <span>EMA 20 / 50</span>
            <span>SMA 200</span>
            <span>ATR 14</span>
          </div>
        </div>
        <div className="auth-assurance">
          <ShieldCheck size={19} />
          <span>Invite-only access · Signals only · No exchange orders</span>
        </div>
      </section>
      <section className="auth-form-panel" aria-labelledby="sign-in-title">
        <div className="auth-form-wrap">
          <span className="auth-lock">
            <LockKeyhole size={22} />
          </span>
          <span className="eyebrow">PRIVATE WORKSPACE</span>
          <h2 id="sign-in-title">
            {invitation ? "Accept your invitation" : "Welcome back"}
          </h2>
          <p>
            {invitation
              ? "Use the email your invitation was issued to. Choose a password of at least 15 characters."
              : "Sign in to follow your markets and review the latest evidence."}
          </p>
          <form onSubmit={submit} className="access-form">
            {invitation && (
              <label>
                Your name
                <input
                  disabled={!ready || busy}
                  required
                  autoComplete="name"
                  maxLength={80}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
            )}
            <label>
              Email address
              <input
                disabled={!ready || busy}
                type="email"
                required
                autoComplete="email"
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Password
              <input
                disabled={!ready || busy}
                type="password"
                required
                autoComplete={invitation ? "new-password" : "current-password"}
                minLength={invitation ? 15 : 1}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="signal-alert">
                {error}
              </p>
            )}
            <button className="primary-button" disabled={busy || !ready}>
              {busy
                ? "Please wait…"
                : invitation
                  ? "Create account"
                  : "Sign in"}
              <ArrowRight size={17} />
            </button>
          </form>
          <p className="auth-help">
            Access is granted by your workspace administrator. Contact them for
            a new invitation or account recovery.
          </p>
        </div>
      </section>
    </main>
  );
}
