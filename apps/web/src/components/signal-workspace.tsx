"use client";
import { formatIST } from "@/lib/time";
import { useEffect, useRef, useState } from "react";
import { SignalChart } from "./signal-chart";
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Download,
  Radio,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { displayPrice } from "@/lib/market-types";
import {
  canHold,
  reasonLabel,
  statusAt,
  type EngineSignal,
  type SignalFeedState,
} from "@/lib/signals";

const price = (
  signal: EngineSignal,
  key:
    | "entry"
    | "stop"
    | "target"
    | "tp1"
    | "tp2"
    | "tp3"
    | "frozen_atr"
    | "risk_distance",
) => displayPrice(Number(signal[key] ?? signal.target), signal.tick_size);
const labels: Record<string, string> = {
  order_1h: "1H EMA20 / EMA50 / SMA200 ordering",
  previous_close: "Previous close on the pullback side of EMA20",
  reclaim: "Completed 1H close reclaimed EMA20",
  loss: "Completed 1H close lost EMA20",
  order_4h: "Required completed 4H trend agrees",
  close_4h: "4H close beyond EMA20 in the signal direction",
  positive_atr: "Source ATR14 is positive",
  ema20_ema50_1h: "1H EMA20 / EMA50 direction agrees",
  ema50_slope_1h: "1H EMA50 slope agrees with direction",
  price_sma200_1h: "Price is on the directional side of SMA200",
  established_1h: "Full 1H EMA20 / EMA50 / SMA200 ordering",
  ema20_ema50_4h: "Completed 4H EMA20 / EMA50 direction agrees",
  ema20_side_4h: "Completed 4H close is beyond EMA20",
  established_4h: "Full completed 4H EMA20 / EMA50 / SMA200 ordering",
  pullback_side: "Previous 1H close reached the EMA20 pullback side",
  pullback_depth_atr: "Pullback depth remains controlled",
  reclaim_strength_atr: "EMA20 reclaim / loss has sufficient strength",
  directional_body: "Source candle body agrees with direction",
  body_atr: "Source candle body is meaningful versus ATR",
  close_location: "Source candle closes strongly in its direction",
  source_extension_atr: "Source close is not overextended from EMA20",
  structure_break: "Source close breaks recent 1H structure",
  recent_run_atr: "Recent six-hour directional run remains within the anti-chase limit",
};

function saveFile(text: string, filename: string, mime: string) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function SignalDetails({
  signal,
  feed,
  dialog,
  titleId,
  canOperate = true,
}: {
  signal: EngineSignal | null;
  feed: SignalFeedState;
  dialog: React.RefObject<HTMLDialogElement | null>;
  titleId: string;
  canOperate?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    const sync = () => setOpen(node.open);
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(node, { attributes: true, attributeFilter: ["open"] });
    return () => observer.disconnect();
  }, [dialog]);
  async function action(action: "hold" | "release") {
    if (!signal || busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/signals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: signal.id,
          action,
          note: note || "Reported by workspace operator",
        }),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          result.detail || result.error || "Could not update signal state",
        );
      await feed.refresh();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Could not update signal state",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="modal signal-detail"
      aria-labelledby={titleId}
      onClose={() => {
        setError(null);
        setNote("");
      }}
    >
      <div className="modal-head">
        <div>
          <span className="eyebrow">PERSISTED ENGINE EVIDENCE</span>
          <h2 id={titleId}>
            {signal
              ? `${signal.symbol.replace("USDT", "")} / USDT · ${signal.direction}`
              : "Signal evidence"}
          </h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close signal evidence"
          onClick={() => dialog.current?.close()}
        >
          <X size={20} />
        </button>
      </div>
      {signal && (
        <>
          <div className="signal-detail-status">
            <span
              className={`status-badge ${statusAt(signal, feed.now) === "active" ? "connected" : "expired"}`}
            >
              {statusAt(signal, feed.now)}
            </span>
            <span className="tag">{signal.strategy}</span>
          </div>
          {(feed.error || signal.source_revised || !signal.integrity_valid) && (
            <p className="signal-alert" role="alert">
              {!signal.integrity_valid
                ? "Stored plan or evidence checksum does not match. Entry actions are disabled."
                : signal.source_revised
                  ? "Source data changed after publication. This setup is withdrawn; its original levels remain on record."
                  : feed.error}
            </p>
          )}
          <div className="signal-levels">
            <div>
              <span>Entry reference · {signal.entry_side}</span>
              <strong>${price(signal, "entry")}</strong>
            </div>
            <div>
              <span>Frozen stop</span>
              <strong>${price(signal, "stop")}</strong>
            </div>
            {signal.tp1 && signal.tp2 && signal.tp3 ? (
              <>
                <div>
                  <span>TP1 · 30% · +1R</span>
                  <strong>${price(signal, "tp1")}</strong>
                </div>
                <div>
                  <span>TP2 · 30% · +1.5R</span>
                  <strong>${price(signal, "tp2")}</strong>
                </div>
                <div>
                  <span>TP3 · 40% · +2R</span>
                  <strong>${price(signal, "tp3")}</strong>
                </div>
              </>
            ) : (
              <div>
                <span>Full target</span>
                <strong>${price(signal, "target")}</strong>
              </div>
            )}
          </div>
          {signal.exit_management && (
            <p className="signal-management-note">
              After TP1, move the remaining stop to entry. After TP2, move the
              remaining stop to TP1. Reference management only; MV does not
              execute orders or record fills.
            </p>
          )}
          <div className="signal-facts">
            <span>
              Frozen ATR14 <b>{price(signal, "frozen_atr")}</b>
            </span>
            <span>
              Risk distance <b>{price(signal, "risk_distance")}</b>
            </span>
            <span>
              Reward / risk <b>{Number(signal.reward_risk).toFixed(2)} R</b>
            </span>
          </div>
          {open && signal.integrity_valid && (
            <SignalChart key={signal.id} signal={signal} />
          )}
          <div className="signal-timestamps">
            <p>
              <span>Source close</span>
              <b>{formatIST(signal.source_close_boundary)}</b>
            </p>
            <p>
              <span>4H confirmation opened</span>
              <b>{formatIST(signal.confirmation_open_time)}</b>
            </p>
            <p>
              <span>Reference quote</span>
              <b>{formatIST(signal.quote_time)}</b>
            </p>
            <p>
              <span>Published</span>
              <b>{formatIST(signal.published_at)}</b>
            </p>
            <p>
              <span>Entry window ends</span>
              <b>{formatIST(signal.expires_at)}</b>
            </p>
          </div>
          <h3 className="signal-section-title">Rule evidence</h3>
          <div className="signal-rule-checks">
            {signal.evidence.checks
              .filter(
                (rule) =>
                  rule.id.startsWith(signal.direction + ".") ||
                  rule.id === "positive_atr",
              )
              .map((rule) => (
                <div key={rule.id}>
                  <CheckCircle2
                    size={16}
                    className={rule.passed ? "positive" : "negative"}
                  />
                  <span>{labels[rule.id.split(".").at(-1)!] || rule.id}</span>
                  <b>{rule.passed ? "Passed" : "Failed"}</b>
                </div>
              ))}
          </div>
          <div
            className="table-scroll signal-snapshot-table"
            tabIndex={0}
            role="region"
            aria-label="Exact indicator snapshot values"
          >
            <table>
              <thead>
                <tr>
                  <th>Snapshot</th>
                  <th>Close</th>
                  <th>EMA20</th>
                  <th>EMA50</th>
                  <th>SMA200</th>
                  <th>ATR14</th>
                </tr>
              </thead>
              <tbody>
                {(["previous", "source", "confirmation"] as const).map(
                  (key) => {
                    const snapshot = signal.evidence[key];
                    return (
                      <tr key={key}>
                        <td>
                          {key === "previous"
                            ? "Previous 1H"
                            : key === "source"
                              ? "Source 1H"
                              : "Required 4H"}
                        </td>
                        <td>{snapshot.ohlcv.close}</td>
                        <td>{snapshot.ema20}</td>
                        <td>{snapshot.ema50}</td>
                        <td>{snapshot.sma200}</td>
                        <td>{snapshot.atr}</td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>
          <p className="signal-provenance">
            {signal.evidence.decimal_precision}-digit Decimal arithmetic ·{" "}
            {signal.risk_policy}
            <br />
            Bid {signal.evidence.quote.bid} / ask {signal.evidence.quote.ask} ·
            tick {signal.tick_size}
          </p>
          <details className="signal-guard-details">
            <summary>Publication guards and evidence identity</summary>
            <ul>
              {Object.entries(signal.evidence.guards).map(([name, passed]) => (
                <li key={name}>
                  {name.replaceAll("_", " ")} · {passed ? "passed" : "failed"}
                </li>
              ))}
            </ul>
            <p>
              Signal ID <code>{signal.id}</code>
            </p>
            <p>
              Evidence SHA-256 <code>{signal.evidence_hash}</code>
            </p>
            <p>
              Plan SHA-256 <code>{signal.plan_hash}</code>
            </p>
            <p>
              Contract SHA-256 <code>{signal.evidence.contract_hash}</code>
            </p>
          </details>
          <section className="ai-preview" aria-label="AI evidence commentary">
            <ShieldCheck size={18} />
            <div>
              <h3>AI evidence commentary</h3>
              <span className="tag">
                {(
                  signal.ai_review?.status ||
                  signal.ai ||
                  "not-configured"
                ).replaceAll("-", " ")}
              </span>
              {signal.ai_review?.status === "complete" &&
              signal.ai_review.summary &&
              !signal.source_revised &&
              signal.integrity_valid ? (
                <>
                  <p>{signal.ai_review.summary}</p>
                  <ul>
                    {signal.ai_review.limitations?.map((text) => (
                      <li key={text}>{text}</li>
                    ))}
                  </ul>
                  <p className="small-text muted">
                    Model commentary · {signal.ai_review.model} · Financial
                    levels are fixed by the strategy engine.
                  </p>
                </>
              ) : (
                <p>
                  The backend rule checks above explain this signal. AI
                  commentary appears after review; its availability does not
                  affect publication or frozen levels.
                </p>
              )}
            </div>
          </section>
          <div className="signal-operator">
            <h3>Position slot</h3>
            <p>
              V3 automatically suppresses another signal in the same direction
              for this coin during the same IST session. Marking a position as
              held additionally blocks any new signal for this coin until you
              release it. This records operator state only; no order or fill is
              recorded.
            </p>
            <label>
              State note
              <input
                value={note}
                disabled={!canOperate}
                maxLength={200}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Optional note for the audit trail"
              />
            </label>
            <div className="signal-actions">
              {signal.slot === "reserved" && (
                <button
                  className="primary-button"
                  disabled={!canOperate || busy || !canHold(signal, feed)}
                  onClick={() => void action("hold")}
                >
                  {busy ? "Saving…" : "Mark as held"}
                </button>
              )}
              {signal.slot && (
                <button
                  className="secondary-button"
                  disabled={!canOperate || busy || !!feed.error}
                  onClick={() => void action("release")}
                >
                  Release signal slot
                </button>
              )}
              <button
                className="text-button"
                onClick={() =>
                  saveFile(
                    JSON.stringify(signal, null, 2),
                    `mv-signal-${signal.id.slice(0, 12)}.json`,
                    "application/json",
                  )
                }
              >
                <Download size={14} />
                Download evidence
              </button>
            </div>
            {error && (
              <p className="signal-alert" role="alert">
                {error}
              </p>
            )}
          </div>
          <h3 className="signal-section-title">Audit events</h3>
          <div className="signal-events">
            {signal.events.map((event, index) => (
              <p key={`${event.type}-${index}`}>
                <b>{event.type.replaceAll("-", " ")}</b>
                <span>{formatIST(event.time)}</span>
              </p>
            ))}
          </div>
          <p className="signal-provenance">
            Entry references are publication snapshots. AI review and Telegram
            delivery are not configured. Historical tests have not demonstrated
            reliable profitability.
          </p>
        </>
      )}
    </dialog>
  );
}

export function LiveSignalPanel({
  feed,
  canOperate = true,
}: {
  feed: SignalFeedState;
  canOperate?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const signal =
    (feed.data?.signals || []).reduce<EngineSignal | null>(
      (latest, row) =>
        !latest || row.published_at > latest.published_at ? row : latest,
      null,
    );
  const decision = feed.data?.decisions[0];
  const ready = !feed.error && feed.data?.engine.ready;
  return (
    <>
      <section className="panel setup-panel live-signal-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">SIGNAL WORKSPACE</span>
            <h2>{signal ? "Latest engine signal" : "Signal monitor"}</h2>
          </div>
          <span className={`tag ${ready ? "long-tag" : ""}`}>
            {ready
              ? feed.data?.engine.session?.open === false
                ? "Session paused"
                : "Engine running"
              : "Waiting"}
          </span>
        </div>
        {feed.data?.safety && feed.data.safety.status !== "normal" && (
          <p className="signal-alert" role="alert">
            <strong>Market Safety Mode</strong> · {feed.data.safety.message}
          </p>
        )}
        {signal ? (
          <>
            <div className="setup-direction">
              <span className="direction-icon">
                {signal.direction === "long" ? (
                  <ArrowUpRight size={25} />
                ) : (
                  <ArrowDownLeft size={25} />
                )}
              </span>
              <div>
                <strong>
                  {signal.symbol.replace("USDT", "")} / USDT{" "}
                  <span
                    className={`tag ${signal.direction === "long" ? "long-tag" : "short-tag"}`}
                  >
                    {signal.direction}
                  </span>
                </strong>
                <p>
                  {signal.setup_type === "momentum_breakout"
                    ? "1H momentum breakout · completed 4H trend"
                    : signal.setup_type === "pullback_continuation"
                      ? "1H pullback continuation · completed 4H trend"
                      : "1H trend setup · completed 4H trend"}
                </p>
              </div>
            </div>
            <div className="level-grid">
              <div>
                <span>Entry reference</span>
                <strong>${price(signal, "entry")}</strong>
              </div>
              <div>
                <span>Reward / risk</span>
                <strong>{Number(signal.reward_risk).toFixed(2)} R</strong>
              </div>
            </div>
            <div className="signal-panel-levels">
              <span>
                Stop <b>${price(signal, "stop")}</b>
              </span>
              {signal.tp1 && signal.tp2 && signal.tp3 ? (
                <>
                  <span>
                    TP1 · 30% <b>${price(signal, "tp1")}</b>
                  </span>
                  <span>
                    TP2 · 30% <b>${price(signal, "tp2")}</b>
                  </span>
                  <span>
                    TP3 · 40% <b>${price(signal, "tp3")}</b>
                  </span>
                </>
              ) : (
                <span>
                  Target <b>${price(signal, "target")}</b>
                </span>
              )}
            </div>
            <div className="setup-rule">
              <ShieldCheck size={16} />
              <span>Frozen ATR14 · {statusAt(signal, feed.now)}</span>
            </div>
            <p className="setup-note">
              <Clock3 size={12} />
              {statusAt(signal, feed.now) === "active"
                ? `Entry window: ${Math.max(0, Math.ceil((signal.expires_at - feed.now) / 1000))}s left`
                : signal.slot === "held"
                  ? "Held slot blocks new signals until released"
                  : "Historical plan · entry window is closed"}
            </p>
            {feed.error && (
              <p className="signal-alert">
                Feed unavailable · entry actions paused
              </p>
            )}
            <button
              className="primary-button"
              onClick={() => dialog.current?.showModal()}
            >
              Inspect signal
              <ArrowRight size={16} />
            </button>
          </>
        ) : (
          <div className="signal-monitor-empty">
            <Radio size={28} />
            <h3>
              {feed.error
                ? "Signal feed unavailable"
                : "Waiting for a qualifying setup"}
            </h3>
            <p>
              Scanning completed 1H candles for qualified pullback
              continuations and structural momentum breakouts with matching 4H
              trend confirmation, completed BTC 15-minute timing and portfolio
              concentration safeguards.
            </p>
            {decision && (
              <span className="signal-decision-note">
                {reasonLabel(decision.reason)}
              </span>
            )}
            <small>
              {feed.error || "No synthetic signal is shown in Binance mode."}
            </small>
          </div>
        )}
      </section>
      <SignalDetails
        canOperate={canOperate}
        signal={signal}
        feed={feed}
        dialog={dialog}
        titleId="panel-signal-title"
      />
    </>
  );
}

export function SignalJournal({
  feed,
  full,
  onOpenJournal,
  canOperate = true,
  emptyMessage = "No signals published yet",
}: {
  feed: SignalFeedState;
  full: boolean;
  onOpenJournal: () => void;
  canOperate?: boolean;
  emptyMessage?: string;
}) {
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const signals = (feed.data?.signals || []).filter(
    (row) =>
      (direction === "all" || row.direction === direction) &&
      `${row.symbol} ${row.id}`.toLowerCase().includes(search.toLowerCase()),
  );
  const visible = full ? signals : signals.slice(0, 5);
  const selectedSignal =
    feed.data?.signals.find((row) => row.id === selected) || null;
  function exportCsv() {
    const columns = [
      "id",
      "symbol",
      "direction",
      "source_close_boundary",
      "published_at",
      "expires_at",
      "entry",
      "stop",
      "target",
      "frozen_atr",
      "risk_distance",
      "reward_risk",
      "quote_time",
      "evidence_hash",
      "status",
    ] as const;
    const rows = signals.map((row) =>
      columns
        .map((key) =>
          String(key === "status" ? statusAt(row, feed.now) : row[key]),
        )
        .join(","),
    );
    saveFile(
      [columns.join(","), ...rows].join("\r\n"),
      "mv-signal-engine-journal.csv",
      "text/csv;charset=utf-8",
    );
  }
  return (
    <>
      <section className="panel journal-panel live-signal-journal">
        <div className="panel-head">
          <div>
            <span className="eyebrow">ENGINE AUDIT TRAIL</span>
            <h2>{full ? "Signal journal" : "Recent signals"}</h2>
          </div>
          <div className="head-actions">
            <span className="tag">Persisted plans</span>
            {full ? (
              <button className="text-button" onClick={exportCsv}>
                <Download size={14} />
                Export CSV
              </button>
            ) : (
              <button className="text-button" onClick={onOpenJournal}>
                View journal
                <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
        {feed.error && (
          <p className="signal-alert" role="alert">
            {feed.error}
          </p>
        )}
        {full && (
          <div className="table-filters">
            <label className="search-field">
              <Search size={16} />
              <input
                aria-label="Search engine journal"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search symbol or signal ID"
              />
            </label>
            <select
              className="signal-filter"
              aria-label="Filter engine direction"
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="all">All directions</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </div>
        )}
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Engine signal history"
        >
          <table>
            <thead>
              <tr>
                <th>Market / signal ID</th>
                <th>Direction</th>
                <th>Entry / stop / targets</th>
                <th>Source close · IST</th>
                <th>Status</th>
                <th>
                  <span className="sr-only">Evidence</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((signal) => (
                <tr key={signal.id}>
                  <td>
                    <span className="table-symbol">
                      {signal.symbol.replace("USDT", "")} <span>/ USDT</span>
                    </span>
                    <small className="record-id">
                      {signal.id.slice(0, 12)}
                    </small>
                  </td>
                  <td
                    className={
                      signal.direction === "long" ? "positive" : "negative"
                    }
                  >
                    {signal.direction}
                  </td>
                  <td className="signal-journal-prices">
                    ${price(signal, "entry")}
                    <small>
                      {signal.tp1 && signal.tp2 && signal.tp3
                        ? `S ${price(signal, "stop")} · T1 ${price(signal, "tp1")} · T2 ${price(signal, "tp2")} · T3 ${price(signal, "tp3")}`
                        : `S ${price(signal, "stop")} · T ${price(signal, "target")}`}
                    </small>
                  </td>
                  <td className="muted">
                    {formatIST(signal.source_close_boundary)}
                  </td>
                  <td>
                    <span
                      className={`status-badge ${statusAt(signal, feed.now) === "active" ? "connected" : "expired"}`}
                    >
                      <i />
                      {statusAt(signal, feed.now)}
                    </span>
                  </td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`Inspect signal ${signal.id.slice(0, 12)}`}
                      onClick={() => {
                        setSelected(signal.id);
                        dialog.current?.showModal();
                      }}
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!visible.length && (
          <div className="signal-journal-empty">
            <Radio size={22} />
            <strong>
              {search || direction !== "all"
                ? "No signals match your filters"
                : emptyMessage}
            </strong>
            <p>
              Only committed backend plans appear here. Ordinary trends and
              rejected setups do not create entry signals.
            </p>
          </div>
        )}
        <p className="journal-note">
          Frozen reference plans · operator state is separate from exchange
          fills · no performance claims
        </p>
      </section>
      {full && (
        <section className="panel decision-panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">EVERY CLOSED-CANDLE DECISION</span>
              <h2>Evaluation log</h2>
            </div>
            <span className="tag">Latest 25</span>
          </div>
          <div className="decision-list">
            {feed.data?.decisions.length ? (
              feed.data.decisions.map((row) => (
                <div key={row.id}>
                  <strong>
                    {row.symbol.replace("USDT", "")}
                    <small>{formatIST(row.source_open_time + 3_600_000)}</small>
                  </strong>
                  <span>{reasonLabel(row.reason)}</span>
                  <span className="tag">{row.outcome.toLowerCase()}</span>
                </div>
              ))
            ) : (
              <p>Waiting for the worker to establish its baseline.</p>
            )}
          </div>
        </section>
      )}
      <SignalDetails
        canOperate={canOperate}
        signal={selectedSignal}
        feed={feed}
        dialog={dialog}
        titleId="journal-signal-title"
      />
    </>
  );
}
