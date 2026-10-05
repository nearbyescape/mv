"use client";
import { formatIST, istDateKey } from "@/lib/time";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check, RefreshCw } from "lucide-react";
import { type EngineSignal, type SignalFeedState } from "@/lib/signals";
import { SignalJournal } from "./signal-workspace";

type Cursor = { before_time: number; before_id: string };
type Notice = {
  id: string;
  signal_id: string;
  symbol: string;
  direction: string;
  type: string;
  created_at: number;
  read: boolean;
  status: string;
  entry_actionable: boolean;
};

export function NotificationInbox({
  authenticated,
  onJournal,
}: {
  authenticated: boolean;
  onJournal: () => void;
}) {
  const generation = useRef(0);
  const [items, setItems] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState("");
  const [next, setNext] = useState<Cursor | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (cursor?: Cursor, refresh = false) => {
    const requestId = ++generation.current;
    setBusy(true);
    try {
      const params = new URLSearchParams(
        cursor
          ? {
              before_time: String(cursor.before_time),
              before_id: cursor.before_id,
            }
          : {},
      );
      const response = await fetch(`/api/notifications?${params}`, {
        cache: "no-store",
      });
      if (response.status === 401) location.assign("/login");
      if (!response.ok) throw new Error("Notification service unavailable");
      const result = await response.json();
      if (requestId !== generation.current) return;
      setItems((old) =>
        cursor || refresh
          ? [...result.notifications, ...old]
              .sort(
                (a, b) =>
                  b.created_at - a.created_at || b.id.localeCompare(a.id),
              )
              .filter((n, i, all) => all.findIndex((x) => x.id === n.id) === i)
          : result.notifications,
      );
      setUnread(result.unread);
      if (!refresh) setNext(result.next);
      setError("");
    } catch (e) {
      if (requestId === generation.current)
        setError(e instanceof Error ? e.message : "Notifications unavailable");
    } finally {
      if (requestId === generation.current) setBusy(false);
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    const polling = setInterval(() => void load(undefined, true), 8000);
    return () => {
      clearTimeout(timer);
      clearInterval(polling);
      generation.current += 1;
    };
  }, [load]);
  async function read(id: string) {
    try {
      const response = await fetch("/api/notifications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      if (response.status === 401) location.assign("/login");
      if (!response.ok) throw new Error("Could not save read status");
      setItems((old) =>
        old.map((n) => (n.id === id ? { ...n, read: true } : n)),
      );
      setUnread((old) => Math.max(0, old - 1));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not acknowledge notification",
      );
    }
  }
  return (
    <div className="access-workspace">
      <section className="research-notice">
        <Bell size={22} />
        <div>
          <strong>Every event, kept on record</strong>
          <p>
            Published plans, expiry, withdrawals and operator changes arrive
            here. Read status is private to your account. Open the journal for
            frozen evidence and current entry guards.
          </p>
        </div>
      </section>
      <section className="panel inbox-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">PERSISTED WEB DELIVERY</span>
            <h2>
              Signal inbox <span className="tag">{unread} unread</span>
            </h2>
          </div>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void load()}
          >
            <RefreshCw size={15} />
            Refresh inbox
          </button>
        </div>
        {error && (
          <p className="signal-alert" role="alert">
            {error}
          </p>
        )}
        {!items.length && (
          <div className="access-empty">
            <Bell size={30} />
            <h3>{busy ? "Loading events…" : "No signal events yet"}</h3>
            <p>
              A committed backend signal creates its delivery record
              automatically.
            </p>
          </div>
        )}
        {items.map((n) => (
          <article
            key={n.id}
            className={`inbox-item ${n.read ? "read" : "unread"}`}
          >
            <span className="inbox-dot" />
            <div>
              <div className="inbox-title">
                <strong>
                  {n.symbol.replace("USDT", "")} / USDT{" "}
                  <span
                    className={n.direction === "long" ? "positive" : "negative"}
                  >
                    {n.direction}
                  </span>
                </strong>
                <span className="tag">
                  {n.type.replaceAll("-", " ").replaceAll("_", " ")}
                </span>
              </div>
              <p>
                {formatIST(n.created_at)} · Current signal: {n.status}
              </p>
              <small>
                {n.entry_actionable
                  ? "Entry guards currently permit review."
                  : "Historical event; consult the current signal guards."}
              </small>
              <div className="inbox-actions">
                <button className="text-button" onClick={onJournal}>
                  Open signal journal
                </button>
                {!n.read && authenticated && (
                  <button
                    className="text-button"
                    onClick={() => void read(n.id)}
                  >
                    <Check size={14} />
                    Mark as read
                  </button>
                )}
              </div>
            </div>
          </article>
        ))}
        {next && (
          <div className="history-pagination">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => void load(next)}
            >
              Load older events
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

export function SignalHistory({
  feed,
  symbols,
}: {
  feed: SignalFeedState;
  symbols: string[];
}) {
  const generation = useRef(0);
  const [items, setItems] = useState<EngineSignal[]>([]);
  const [symbol, setSymbol] = useState("");
  const [direction, setDirection] = useState("");
  // null follows today's IST date, including midnight rollover; "" shows all dates.
  const [date, setDate] = useState<string | null>(null);
  const today = istDateKey(feed.now);
  const activeDate = date ?? today;
  const [next, setNext] = useState<Cursor | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    async (cursor?: Cursor) => {
      const requestId = ++generation.current;
      setBusy(true);
      if (!cursor) {
        setItems([]);
        setNext(null);
      }
      try {
        const params = new URLSearchParams({
          ...(symbol ? { symbol } : {}),
          ...(direction ? { direction } : {}),
          ...(activeDate ? { date: activeDate } : {}),
          ...(cursor
            ? {
                before_time: String(cursor.before_time),
                before_id: cursor.before_id,
              }
            : {}),
        });
        const response = await fetch(`/api/history?${params}`, {
          cache: "no-store",
        });
        if (response.status === 401) location.assign("/login");
        if (!response.ok) throw new Error("History service unavailable");
        const result = await response.json();
        if (requestId !== generation.current) return;
        setItems((old) =>
          cursor
            ? [...old, ...result.signals].filter(
                (n, i, all) => all.findIndex((x) => x.id === n.id) === i,
              )
            : result.signals,
        );
        setNext(result.next);
        setError("");
      } catch (e) {
        if (requestId === generation.current)
          setError(e instanceof Error ? e.message : "History unavailable");
      } finally {
        if (requestId === generation.current) setBusy(false);
      }
    },
    [symbol, direction, activeDate],
  );
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => {
      clearTimeout(timer);
      generation.current += 1;
    };
  }, [load]);
  const historyFeed = {
    ...feed,
    error: error || feed.error,
    data: feed.data ? { ...feed.data, signals: items } : null,
  };
  return (
    <>
      <section className="panel history-controls">
        <div>
          <span className="eyebrow">COMPLETE PERSISTED HISTORY</span>
          <p>
            Showing signals by publication date in IST. Choose a date to browse
            earlier plans. Evidence actions here are read-only; manage current
            slots from the overview.
          </p>
        </div>
        <div className="history-controls-actions">
          <label>
            Date · IST
            <input
              type="date"
              aria-label="History date in IST"
              value={activeDate}
              max={today}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
          <div className="segmented" aria-label="History date selection">
            <button
              className={date === null ? "selected" : ""}
              aria-pressed={date === null}
              onClick={() => setDate(null)}
            >
              Today
            </button>
            <button
              className={date === "" ? "selected" : ""}
              aria-pressed={date === ""}
              onClick={() => setDate("")}
            >
              All dates
            </button>
          </div>
          <label>
            Market
            <select
              aria-label="History market"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              <option value="">All markets</option>
              {Array.from(
                new Set([
                  ...symbols,
                  ...items.map((i) => i.symbol),
                  ...(symbol ? [symbol] : []),
                ]),
              ).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Direction
            <select
              aria-label="History direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option value="">All directions</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </label>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void load()}
          >
            <RefreshCw size={15} />
            Refresh history
          </button>
        </div>
      </section>
      <SignalJournal
        feed={historyFeed}
        full
        canOperate={false}
        emptyMessage={
          busy
            ? "Loading signals…"
            : error
              ? "Signal history unavailable"
              : activeDate
                ? "No signals published on this date"
                : "No signals published yet"
        }
        onOpenJournal={() => {}}
      />
      <div className="history-pagination">
        <span>
          {items.length} plans loaded
          {activeDate ? ` · ${activeDate} IST` : " · All dates"} · CSV exports
          the loaded, searched rows.
        </span>
        {next ? (
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void load(next)}
          >
            {busy ? "Loading…" : "Load older signals"}
          </button>
        ) : (
          <span>{busy ? "Loading…" : "End of history"}</span>
        )}
      </div>
    </>
  );
}
