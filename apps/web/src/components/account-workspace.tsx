"use client";
import { formatIST } from "@/lib/time";
import { useCallback, useEffect, useState } from "react";
import { Copy, Plus, ShieldCheck } from "lucide-react";


export type Account = {
  id: string;
  email: string;
  name: string;
  role: "admin" | "operator" | "viewer";
  enabled: boolean;
  created_at: number;
};
type Invitation = {
  id: string;
  email: string;
  role: string;
  expires_at: number;
  used_at: number | null;
};
type Audit = {
  id: string;
  actor_id: string | null;
  action: string;
  time: number;
  detail: Record<string, unknown>;
};

async function request(path: string, init?: RequestInit) {
  const response = await fetch(path, { cache: "no-store", ...init });
  if (response.status === 401) location.assign("/login");
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : result.error || "Request failed",
    );
  return result;
}

export function AccountWorkspace({ user }: { user: Account }) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function change(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await request("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: current,
          new_password: password,
        }),
      });
      setCurrent("");
      setPassword("");
      setMessage("Password changed. Your other sessions have been signed out.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not change password");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel access-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">YOUR ACCOUNT</span>
          <h2>{user.name}</h2>
        </div>
        <span className="tag">{user.role}</span>
      </div>
      <p>{user.email}</p>
      <form className="access-form" onSubmit={change}>
        <h3>Change password</h3>
        <label>
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label>
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={15}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <span className="muted-copy">
          Use at least 15 characters. Changing it revokes all existing sessions.
        </span>
        <button className="primary-button" disabled={busy}>
          {busy ? "Saving…" : "Update password"}
        </button>
        {message && <p role="status">{message}</p>}
      </form>
    </section>
  );
}

export function Administration() {
  const [now, setNow] = useState(0);
  const [users, setUsers] = useState<Account[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [accounts, trail] = await Promise.all([
        request("/api/admin"),
        request("/api/admin?section=audit"),
      ]);
      setUsers(accounts.users);
      setInvites(accounts.invites);
      setAudit(trail.events);
      setNow(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Administration unavailable");
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);
  async function mutate(body: object, method = "POST") {
    setBusy(true);
    setError("");
    try {
      const result = await request("/api/admin", {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (result.accept_url) {
        setLink(result.accept_url);
        setEmail("");
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="access-workspace">
      <section className="research-notice">
        <ShieldCheck size={22} />
        <div>
          <strong>Private access, clear responsibilities</strong>
          <p>
            Viewers read evidence. Operators manage markets and held slots.
            Administrators manage accounts. Account changes immediately revoke
            that user’s sessions.
          </p>
        </div>
      </section>
      {error && (
        <p className="signal-alert" role="alert">
          {error}
        </p>
      )}
      <section className="panel access-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">INVITE ONLY</span>
            <h2>Invite a member</h2>
          </div>
        </div>
        <form
          className="invite-form"
          onSubmit={(e) => {
            e.preventDefault();
            void mutate({ email, role });
          }}
        >
          <label>
            Email address
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Access role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
              <option value="admin">Administrator</option>
            </select>
          </label>
          <button className="primary-button" disabled={busy}>
            <Plus size={16} />
            Create invitation
          </button>
        </form>
        {link && (
          <div className="invitation-link">
            <p>
              Valid for 24 hours, one use. Copy this private link and share it
              with the invited person.
            </p>
            <input aria-label="Private invitation link" readOnly value={link} />
            <button
              className="secondary-button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(link);
                } catch {
                  setError("Select and copy the invitation link manually.");
                }
              }}
            >
              <Copy size={15} />
              Copy link
            </button>
          </div>
        )}
      </section>
      <section className="panel journal-panel">
        <div className="panel-head">
          <h2>Workspace members</h2>
          <span className="tag">{users.length} accounts</span>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Workspace members"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Access</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.name}</strong>
                    <small className="record-id">{u.email}</small>
                  </td>
                  <td>
                    <select
                      aria-label={`Role for ${u.email}`}
                      value={u.role}
                      disabled={busy}
                      onChange={(e) =>
                        void mutate(
                          {
                            id: u.id,
                            role: e.target.value,
                            enabled: u.enabled,
                          },
                          "PATCH",
                        )
                      }
                    >
                      <option value="admin">Administrator</option>
                      <option value="operator">Operator</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  </td>
                  <td>
                    <span
                      className={`status-badge ${u.enabled ? "connected" : "expired"}`}
                    >
                      {u.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        void mutate(
                          { id: u.id, role: u.role, enabled: !u.enabled },
                          "PATCH",
                        )
                      }
                    >
                      {u.enabled ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel journal-panel">
        <div className="panel-head">
          <h2>Recent invitations</h2>
          <span className="tag">Latest 100</span>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Invitations"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Expires · IST</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {invites.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td>{i.role}</td>
                  <td>{formatIST(i.expires_at)}</td>
                  <td>
                    {i.used_at ? (
                      "Used / revoked"
                    ) : i.expires_at <= now ? (
                      "Expired"
                    ) : (
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => void mutate({ id: i.id }, "DELETE")}
                      >
                        Revoke invitation
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel journal-panel">
        <div className="panel-head">
          <h2>Access & operations audit</h2>
          <span className="tag">Latest 100</span>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Access audit"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>Time · IST</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td>{formatIST(a.time)}</td>
                  <td>{a.action.replaceAll("-", " ")}</td>
                  <td>
                    {users.find((u) => u.id === a.actor_id)?.name ||
                      "Server / sign-in"}
                  </td>
                  <td>
                    <span className="audit-detail">
                      {JSON.stringify(a.detail)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
