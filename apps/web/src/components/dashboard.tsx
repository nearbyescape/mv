"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Bell,
  LogOut,
  Users,
  UserRound,
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  CandlestickChart,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  Download,
  FlaskConical,
  LayoutDashboard,
  ListFilter,
  ListPlus,
  Menu,
  Moon,
  Radio,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Target,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import charts from "@/lib/demo-charts.json";
import contract from "../../../../packages/contracts/strategy-v1.json";
import type { DemoSymbol, Timeframe } from "./market-chart";
import { LiveMarketPanel } from "./live-market-panel";
import { LiveSignalPanel, SignalJournal } from "./signal-workspace";
import { ResearchWorkspace } from "./research-workspace";
import { NotificationInbox, SignalHistory } from "./live-operations";
import { PerformanceWorkspace } from "./performance-workspace";
import {
  AccountWorkspace,
  Administration,
  type Account,
} from "./account-workspace";
import { useSignalFeed, type EngineHealth } from "@/lib/signals";
import {
  marketName,
  displayPrice,
  type CollectorHealth,
  type MarketView,
} from "@/lib/market-types";

type Page =
  | "overview"
  | "markets"
  | "signals"
  | "performance"
  | "research"
  | "strategy"
  | "system"
  | "notifications"
  | "account"
  | "admin";
type Health = {
  status: string;
  database: string;
  collector?: CollectorHealth;
  engine?: EngineHealth;
  web_delivery?: { state: string; heartbeat: number | null; backlog: number };
  ready?: boolean;
  backup?: { state: string; completed_at: number | null };
  telegram?: string;
  telegram_delivery?: {
    state: string;
    pending: number;
    delivered: number;
    failed: number;
    unknown: number;
  };
  ai?: string;
  ai_review?: {
    state: string;
    model?: string;
    pending: number;
    daily_requests: number;
    daily_limit: number;
  };
};
const navigation: { id: Page; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "markets", label: "Chosen markets", icon: CandlestickChart },
  { id: "signals", label: "Signal journal", icon: Radio },
  { id: "performance", label: "Performance", icon: Activity },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "account", label: "My account", icon: UserRound },
  { id: "admin", label: "Administration", icon: Users },
  { id: "research", label: "Research", icon: FlaskConical },
  { id: "strategy", label: "Strategy", icon: Workflow },
  { id: "system", label: "System & delivery", icon: Settings2 },
];
const money = (value: number) =>
  value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const samples = [
  {
    id: "DEMO-001",
    symbol: "BTCUSDT" as DemoSymbol,
    direction: "Long",
    status: "Illustrative",
    time: "29 Sep · 05:30 PM IST",
  },
  {
    id: "DEMO-002",
    symbol: "ETHUSDT" as DemoSymbol,
    direction: "Short",
    status: "Expired",
    time: "28 Sep · 01:30 PM IST",
  },
  {
    id: "DEMO-003",
    symbol: "BTCUSDT" as DemoSymbol,
    direction: "Long",
    status: "Cancelled",
    time: "27 Sep · 09:30 PM IST",
  },
];

function Mark({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand-mark ${small ? "small" : ""}`}>
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <path d="m5 22 7-12 7 12 7-12h3" />
      </svg>
    </span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <span className="eyebrow">{children}</span>;
}

async function readFoundation() {
  try {
    const [system, list, marketResponse] = await Promise.all([
      fetch("/api/system", { cache: "no-store" }),
      fetch("/api/watchlist", { cache: "no-store" }),
      fetch("/api/markets", { cache: "no-store" }),
    ]);
    if ([system, list, marketResponse].some((r) => r.status === 401))
      location.assign("/login");
    return {
      health: (await system.json()) as Health,
      symbols: list.ok ? ((await list.json()).symbols as string[]) : null,
      markets: marketResponse.ok
        ? ((await marketResponse.json()).markets as MarketView[])
        : [],
    };
  } catch {
    return {
      health: { status: "offline", database: "unavailable" },
      symbols: null,
      markets: [] as MarketView[],
    };
  }
}

export function Dashboard({
  initialUser,
  authenticationRequired = false,
}: {
  initialUser?: Account;
  authenticationRequired?: boolean;
}) {
  const canOperate = !authenticationRequired || initialUser?.role !== "viewer";
  const visibleNavigation = navigation.filter((n) =>
    n.id === "admin"
      ? authenticationRequired && initialUser?.role === "admin"
      : n.id === "account"
        ? authenticationRequired
        : true,
  );
  const [page, setPage] = useState<Page>("overview");
  const [selectedSymbol, setSymbol] = useState<string>("BTCUSDT");
  const [mode, setMode] = useState<"binance" | "demo">("binance");
  const signalFeed = useSignalFeed(mode === "binance");
  const [markets, setMarkets] = useState<MarketView[]>([]);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [indicators, setIndicators] = useState(["ema20", "ema50", "sma200"]);
  const [dark, setDark] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [watchlist, setWatchlist] = useState<string[]>(["BTCUSDT", "ETHUSDT"]);
  const [listLoaded, setListLoaded] = useState(false);
  const [draft, setDraft] = useState("BTCUSDT, ETHUSDT");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("All directions");
  const [detailId, setDetailId] = useState("DEMO-001");
  const manageDialog = useRef<HTMLDialogElement>(null);
  const detailDialog = useRef<HTMLDialogElement>(null);
  const helpDialog = useRef<HTMLDialogElement>(null);
  const symbol = watchlist.includes(selectedSymbol)
    ? selectedSymbol
    : watchlist[0] || "BTCUSDT";
  const long = detailId !== "DEMO-002";
  const detailSymbol = detailId === "DEMO-002" ? "ETHUSDT" : "BTCUSDT";
  const sampleData = charts[detailSymbol]["1h"];
  const entry = sampleData.candles.at(-1)!.close;
  const sampleAtr = Math.round(sampleData.atr.at(-1)!.value * 100) / 100;
  const stop = Math.round((entry + (long ? -2 : 2) * sampleAtr) * 100) / 100;
  const risk = Math.abs(entry - stop);
  const target = Math.round((entry + (long ? 2 : -2) * risk) * 100) / 100;
  const connected = health?.status === "ok";
  const engine = signalFeed.data?.engine || health?.engine;

  async function refreshSystem() {
    const result = await readFoundation();
    setHealth(result.health);
    setMarkets(result.markets);
    setListLoaded(result.symbols !== null);
    if (result.symbols) setWatchlist(result.symbols);
  }
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      const result = await readFoundation();
      if (!active) return;
      setHealth(result.health);
      setMarkets(result.markets);
      setListLoaded(result.symbols !== null);
      if (result.symbols) setWatchlist(result.symbols);
      timer = setTimeout(load, 15_000);
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  function navigate(next: Page) {
    setPage(next);
    setMenuOpen(false);
    setSearch("");
  }
  function toggleIndicator(key: string) {
    setIndicators((previous) =>
      previous.includes(key)
        ? previous.filter((i) => i !== key)
        : [...previous, key],
    );
  }
  function openManage() {
    setDraft(watchlist.join(", "));
    setMessage("");
    manageDialog.current?.showModal();
  }
  function openDetails(id: string) {
    setDetailId(id);
    detailDialog.current?.showModal();
  }

  async function saveWatchlist() {
    const symbols = draft
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (
      !symbols.length ||
      symbols.length > 30 ||
      symbols.some((s) => !/^[A-Z0-9]{2,20}USDT$/.test(s)) ||
      new Set(symbols).size !== symbols.length
    ) {
      setMessage("Enter 1–30 unique USDT symbols, separated by commas.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch("/api/watchlist", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      });
      if (!response.ok)
        throw new Error("Could not save. Check that the local API is running.");
      const payload = await response.json();
      setWatchlist(payload.symbols);
      setListLoaded(true);
      manageDialog.current?.close();
      setMessage(
        "Chosen coins saved to the database. The collector will validate and warm up changes.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not save chosen coins.",
      );
    } finally {
      setSaving(false);
    }
  }

  function exportJournal() {
    const csv =
      "Source,ID,Symbol,Direction,Status,Time\n" +
      samples
        .map((s) =>
          [
            "SYNTHETIC DEMO",
            s.id,
            s.symbol,
            s.direction,
            s.status,
            s.time,
          ].join(","),
        )
        .join("\n");
    const link = document.createElement("a");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    link.href = url;
    link.download = "mv-signal-demo-journal.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  const filtered = samples.filter(
    (s) =>
      `${s.id} ${s.symbol}`.toLowerCase().includes(search.toLowerCase()) &&
      (direction === "All directions" || s.direction === direction),
  );
  const title = navigation.find((n) => n.id === page)!.label;

  const marketPanel = (
    <LiveMarketPanel
      symbol={symbol}
      setSymbol={setSymbol}
      timeframe={timeframe}
      setTimeframe={setTimeframe}
      indicators={indicators}
      toggleIndicator={toggleIndicator}
      dark={dark}
      watchlist={watchlist}
      mode={mode}
      setMode={setMode}
    />
  );

  const watchPanel = (
    <section className="panel watch-panel">
      <div className="panel-head">
        <div>
          <SectionLabel>YOUR UNIVERSE</SectionLabel>
          <h2>
            Chosen markets <span className="count">{watchlist.length}</span>
          </h2>
        </div>
        <button
          className="icon-button"
          aria-label="Manage chosen coins"
          onClick={openManage}
          disabled={!canOperate}
        >
          <ListPlus size={19} />
        </button>
      </div>
      <div className="watch-labels">
        <span>Market</span>
        <span>{mode === "demo" ? "Sample price" : "Last completed close"}</span>
      </div>
      <div className="watch-list">
        {watchlist.map((s) => {
          const item = markets.find((m) => m.symbol === s);
          const demoPrice = charts[s as DemoSymbol]?.["1h"].candles.at(-1);
          const supported = mode === "demo" ? !!demoPrice : true;
          const c = mode === "demo" ? demoPrice : item?.series.candles.at(-1);
          return (
            <button
              key={s}
              className={`watch-row ${symbol === s ? "active" : ""}`}
              disabled={!supported}
              onClick={() => setSymbol(s)}
            >
              <span
                className={`coin-icon small ${s === "BTCUSDT" ? "btc" : "eth"}`}
              >
                {s === "BTCUSDT" ? "₿" : s === "ETHUSDT" ? "Ξ" : s.slice(0, 1)}
              </span>
              <span className="watch-name">
                <strong>{s.replace("USDT", "")}</strong>
                <small>
                  {supported ? marketName(s) : "Awaiting exchange validation"}
                </small>
              </span>
              <span className="watch-price">
                <strong>
                  {c
                    ? `$${displayPrice(Number(c.close), mode === "binance" ? item?.contract.tick_size : null)}`
                    : "—"}
                </strong>
                <small>
                  {mode === "demo"
                    ? c
                      ? "Synthetic fixture"
                      : "No demo chart"
                    : item?.status.replaceAll("-", " ") ||
                      "Awaiting validation"}
                </small>
              </span>
            </button>
          );
        })}
      </div>
      <button className="watch-add" onClick={openManage} disabled={!canOperate}>
        <ListPlus size={15} />
        Manage chosen coins
        <ArrowRight size={14} />
      </button>
      <p className="panel-note">
        {listLoaded ? "Saved configuration" : "Default preview list"} · Only
        validated, warmed-up contracts are ready.
      </p>
    </section>
  );

  const setupPanel = (
    <section className="panel setup-panel">
      <div className="panel-head">
        <div>
          <SectionLabel>SIGNAL WORKSPACE</SectionLabel>
          <h2>Example setup</h2>
        </div>
        <span className="tag demo-tag">Demo</span>
      </div>
      <div className="setup-direction">
        <span className="direction-icon">
          <ArrowUpRight size={25} />
        </span>
        <div>
          <strong>
            BTC / USDT <span className="tag long-tag">Long</span>
          </strong>
          <p>EMA pullback · 1H entry / 4H trend</p>
        </div>
      </div>
      <div className="level-grid">
        <div>
          <span>Entry reference</span>
          <strong>${money(charts.BTCUSDT["1h"].candles.at(-1)!.close)}</strong>
        </div>
        <div>
          <span>Reward / risk</span>
          <strong>
            2.00<span className="unit">R</span>
          </strong>
        </div>
      </div>
      <div className="setup-rule">
        <ShieldCheck size={16} />
        <span>Frozen ATR stop · Single target</span>
      </div>
      <p className="setup-note">
        An illustrative layout for a future engine signal. No live entry has
        been generated.
      </p>
      <button
        className="primary-button"
        onClick={() => openDetails("DEMO-001")}
      >
        Inspect setup
        <ArrowRight size={16} />
      </button>
    </section>
  );

  const journal = (
    <section className="panel journal-panel">
      <div className="panel-head">
        <div>
          <SectionLabel>AUDIT TRAIL</SectionLabel>
          <h2>{page === "signals" ? "Signal journal" : "Recent examples"}</h2>
        </div>
        <div className="head-actions">
          <span className="tag demo-tag">Synthetic records</span>
          {page === "signals" ? (
            <button className="text-button" onClick={exportJournal}>
              <Download size={14} />
              Export CSV
            </button>
          ) : (
            <button className="text-button" onClick={() => navigate("signals")}>
              View journal
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      </div>
      {page === "signals" && (
        <div className="table-filters">
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="Search journal"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search symbol or record ID"
            />
          </label>
          <label className="filter-select">
            <ListFilter size={15} />
            <select
              aria-label="Filter direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option>All directions</option>
              <option>Long</option>
              <option>Short</option>
            </select>
          </label>
        </div>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Market</th>
              <th>Direction</th>
              <th>Strategy</th>
              <th>Source candle</th>
              <th>Status</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id}>
                <td>
                  <span className="table-symbol">
                    {s.symbol.replace("USDT", "")}
                    <span>/ USDT</span>
                  </span>
                  <small className="record-id">{s.id}</small>
                </td>
                <td>
                  <span
                    className={`direction ${s.direction === "Long" ? "positive" : "negative"}`}
                  >
                    {s.direction === "Long" ? (
                      <ArrowUpRight size={15} />
                    ) : (
                      <ArrowDownLeft size={15} />
                    )}
                    {s.direction}
                  </span>
                </td>
                <td>
                  EMA pullback <span className="muted">v1</span>
                </td>
                <td className="muted">{s.time}</td>
                <td>
                  <span className={`status-badge ${s.status.toLowerCase()}`}>
                    <i />
                    {s.status}
                  </span>
                </td>
                <td>
                  <button
                    className="icon-button"
                    aria-label={`Inspect ${s.id}`}
                    onClick={() => openDetails(s.id)}
                  >
                    <ArrowUpRight size={17} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <div className="empty-state">No examples match your filters.</div>
        )}
      </div>
      <div className="journal-foot">
        Design examples only. Paper results and performance metrics will appear
        after the tracking engine is verified.
      </div>
    </section>
  );

  return (
    <div
      className={`app-shell ${menuOpen ? "mobile-nav-open" : ""}`}
      data-theme={dark ? "dark" : "light"}
    >
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <Mark />
          <span>
            mv<span className="brand-light">signal</span>
            <small>MARKET INTELLIGENCE</small>
          </span>
        </a>
        <button
          className="mobile-nav-close icon-button"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        >
          <X size={20} />
        </button>
        <div className="workspace-label">
          <span className="workspace-dot" />
          PRIVATE WORKSPACE
        </div>
        <nav aria-label="Main navigation">
          {visibleNavigation.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${page === n.id ? "active" : ""}`}
              aria-current={page === n.id ? "page" : undefined}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={19} />
              <span>{n.label}</span>
              {n.id === "signals" && (
                <span className="nav-number">
                  {mode === "demo" ? 3 : signalFeed.data?.signals.length || 0}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="strategy-sidebar">
            <span className="sidebar-eyebrow">THE STRATEGY</span>
            <strong>
              Rules first.
              <br />
              Clarity always.
            </strong>
            <p>
              EMA 20 / 50 · SMA 200
              <br />
              ATR 14 · Closed candles
            </p>
            <button onClick={() => navigate("strategy")}>
              Explore the rulebook
              <ArrowRight size={14} />
            </button>
          </div>
          <div className="sidebar-phase">
            <span className="phase-dot" />
            <div>
              <strong>Live signals & private access</strong>
              <small>Phases 6 & 7 · v0.7.0</small>
            </div>
          </div>
          <button
            className="sidebar-profile"
            onClick={() =>
              authenticationRequired
                ? navigate("account")
                : helpDialog.current?.showModal()
            }
          >
            <span className="avatar">MV</span>
            <span>
              <strong>{initialUser?.name || "Private workspace"}</strong>
              <small>{initialUser?.role || "Development preview"}</small>
            </span>
            <CircleHelp size={16} />
          </button>
        </div>
      </aside>
      {menuOpen && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMenuOpen(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-actions">
            <span className="environment-badge">
              <i />
              {authenticationRequired
                ? "Private · Live signals"
                : "Local preview"}
            </span>
            <button
              className="icon-button"
              aria-label={
                dark ? "Switch to light theme" : "Switch to dark theme"
              }
              onClick={() => setDark(!dark)}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              className="icon-button help-button"
              aria-label="About this preview"
              onClick={() => helpDialog.current?.showModal()}
            >
              <CircleHelp size={18} />
            </button>
            {authenticationRequired && (
              <button
                className="icon-button"
                aria-label="Sign out"
                onClick={async () => {
                  try {
                    await fetch("/api/auth/logout", { method: "POST" });
                  } finally {
                    location.assign("/login");
                  }
                }}
              >
                <LogOut size={18} />
              </button>
            )}
            <span className="top-avatar">
              {initialUser?.name.slice(0, 2).toUpperCase() || "MV"}
            </span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <SectionLabel>YOUR MARKET, IN FOCUS</SectionLabel>
              <h1>{page === "overview" ? "Market overview" : title}</h1>
              <p>
                {page === "overview"
                  ? "A clear view of your markets. Every signal backed by rules."
                  : page === "markets"
                    ? "A focused universe of coins, chosen by you."
                    : page === "signals"
                      ? "Trace every setup from source candle to delivery."
                      : page === "performance"
                        ? "Measure V2 reference outcomes, setup quality and missed moves without changing the live engine."
                      : page === "research"
                        ? "Frozen rules, explicit costs and a reproducible historical record."
                        : page === "strategy"
                          ? "One transparent method. Consistent, reproducible decisions."
                          : "Visibility into the services behind your workspace."}
              </p>
            </div>
            <button
              className="secondary-button"
              onClick={openManage}
              disabled={!canOperate}
            >
              <SlidersHorizontal size={16} />
              Manage markets
            </button>
          </div>
          <div className="preview-banner">
            <span className="preview-icon">
              <Sparkles size={16} />
            </span>
            <p>
              <strong>
                {page === "performance"
                  ? "V2 observational analytics · separate from signal decisions"
                  : page === "research"
                    ? "Historical research · versioned report"
                  : mode === "demo"
                    ? "Design & foundation preview"
                    : engine?.ready && !signalFeed.error
                      ? engine.session?.open === false
                        ? "Binance signals · Session paused"
                        : "Binance signals · Engine running"
                      : "Binance signals · Waiting for engine"}
              </strong>
              <span>
                {page === "performance"
                  ? "Reference outcomes use completed post-publication market data. They never create, suppress or modify a signal."
                  : page === "research"
                    ? "Registered experiments use historical futures data and explicit execution assumptions."
                  : mode === "demo"
                    ? "Charts and signal examples use synthetic data. Engine monitoring continues separately."
                    : engine?.session?.enabled
                      ? "Signals come from backend rules and frozen evidence. New signals run 09:00 AM–11:00 PM IST; AI reviews evidence separately."
                      : "Signals come from backend rules and frozen evidence. AI reviews evidence separately."}
              </span>
            </p>
            <button onClick={() => navigate("system")}>
              Build status
              <ArrowRight size={14} />
            </button>
          </div>
          {message.startsWith("Chosen coins saved") && (
            <div className="notice" role="status">
              {message}
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setMessage("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {page === "overview" && (
            <>
              <div className="summary-grid">
                <div className="summary-card">
                  <span className="summary-icon">
                    <CandlestickChart size={20} />
                  </span>
                  <div>
                    <span>Chosen markets</span>
                    <strong>
                      {String(watchlist.length).padStart(2, "0")}
                      <small>USDT perpetuals</small>
                    </strong>
                  </div>
                  <span className="mini-badge">
                    {listLoaded ? "Saved" : "Defaults"}
                  </span>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">
                    <Clock3 size={20} />
                  </span>
                  <div>
                    <span>Signal timeframes</span>
                    <strong>
                      1H <span className="summary-divider">/</span> 4H
                      <small>Entry / confirmation</small>
                    </strong>
                  </div>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">
                    <Activity size={20} />
                  </span>
                  <div>
                    <span>Market feed</span>
                    <strong className="status-text">
                      {health?.collector?.live ? "Connected" : "Not live"}
                      <small>
                        {health?.collector?.state?.replaceAll("-", " ") ||
                          "Awaiting collector"}
                      </small>
                    </strong>
                  </div>
                  <span className="status-ring" />
                </div>
              </div>
              <div className="overview-grid">
                <div className="chart-column">{marketPanel}</div>
                <div className="right-column">
                  {watchPanel}
                  {mode === "demo" ? (
                    setupPanel
                  ) : (
                    <LiveSignalPanel
                      symbol={symbol}
                      feed={signalFeed}
                      canOperate={canOperate}
                    />
                  )}
                </div>
              </div>
              {mode === "demo" ? (
                journal
              ) : (
                <SignalJournal
                  feed={signalFeed}
                  canOperate={canOperate}
                  full={false}
                  onOpenJournal={() => navigate("signals")}
                />
              )}
              <div className="workflow-strip">
                <span>
                  <ShieldCheck size={17} />
                  Deterministic rules
                </span>
                <ChevronRight size={14} />
                <span>
                  <Database size={17} />
                  One persisted signal
                </span>
                <ChevronRight size={14} />
                <span>
                  <Send size={17} />
                  Web inbox · Telegram planned
                </span>
                <span className="workflow-ai">
                  <Sparkles size={16} />
                  {health?.ai && health.ai !== "not-configured"
                    ? "AI evidence review · " + health.ai
                    : "AI explanations planned"}
                </span>
              </div>
            </>
          )}
          {page === "markets" && (
            <>
              <div className="markets-grid">
                {marketPanel}
                <div>
                  {watchPanel}
                  <div className="info-card">
                    <Target size={22} />
                    <h3>A focused universe</h3>
                    <p>
                      Only chosen symbols will be monitored. New coins must pass
                      Binance contract checks and the 500-candle warm-up in both
                      timeframes.
                    </p>
                    <span className="tag">Contract validation · Phase 3</span>
                  </div>
                </div>
              </div>
            </>
          )}
          {page === "signals" && (
            <>
              {mode === "demo" ? (
                journal
              ) : (
                <SignalHistory feed={signalFeed} symbols={watchlist} />
              )}
              <div className="info-card horizontal">
                <ShieldCheck size={24} />
                <div>
                  <h3>An honest journal, from day one</h3>
                  <p>
                    The engine records published plans and rejected or expired
                    decisions. Held state comes from the workspace operator.
                    Operator-held slots are reported states. No exchange fills
                    or account profit are inferred from them.
                  </p>
                </div>
              </div>
            </>
          )}
          {page === "performance" && <PerformanceWorkspace />}
          {page === "research" && <ResearchWorkspace />}
          {page === "notifications" && (
            <NotificationInbox
              authenticated={authenticationRequired}
              onJournal={() => navigate("signals")}
            />
          )}
          {page === "account" && initialUser && (
            <AccountWorkspace user={initialUser} />
          )}
          {page === "admin" && initialUser?.role === "admin" && (
            <Administration />
          )}
          {page === "strategy" && (
            <>
              <div className="strategy-intro panel">
                <div>
                  <SectionLabel>VERSIONED STRATEGY CONTRACT</SectionLabel>
                  <h2>EMA pullback with ATR risk</h2>
                  <p>
                    Trend alignment sets the direction. A completed candle
                    reclaiming EMA20 triggers the setup. ATR defines its risk.
                  </p>
                  <span className="tag">{contract.id}</span>
                  <span className="tag demo-tag">Unvalidated hypothesis</span>
                </div>
                <div className="strategy-formula">
                  <span>
                    EMA<span>20</span>
                  </span>
                  <span>
                    EMA<span>50</span>
                  </span>
                  <span>
                    SMA<span>200</span>
                  </span>
                  <span>
                    ATR<span>14</span>
                  </span>
                </div>
              </div>
              <div className="rule-grid">
                {[
                  {
                    number: "01",
                    title: "Establish the trend",
                    text: "Long: EMA20 > EMA50 > SMA200. Short: the inverse. The latest completed 4H candle must agree and close beyond EMA20 in the same direction.",
                  },
                  {
                    number: "02",
                    title: "Wait for the reclaim",
                    text: "Long: previous close ≤ previous EMA20, then current close > current EMA20. Short: previous close ≥ EMA20, then current close < EMA20. Only completed 1H candles count.",
                  },
                  {
                    number: "03",
                    title: "Validate the entry",
                    text: "Require 500 warm-up bars per timeframe, contiguous fresh data, a quote no older than 5 seconds, and entry drift ≤ 0.5 ATR. One active setup per coin; entry expires after 5 minutes.",
                  },
                  {
                    number: "04",
                    title: "Freeze the risk",
                    text: "Stop: 2 × source ATR14 from the entry. Full target: 2R using the rounded stop distance. No partial exits or trailing stops. Exit if a completed 1H candle crosses EMA50 against the position.",
                  },
                ].map((r) => (
                  <section className="panel rule-card" key={r.number}>
                    <span className="rule-number">{r.number}</span>
                    <h3>{r.title}</h3>
                    <p>{r.text}</p>
                  </section>
                ))}
              </div>
              <div className="panel ai-contract">
                <Sparkles size={24} />
                <div>
                  <h3>DeepSeek reviews the evidence</h3>
                  <p>
                    The backend generates signals using this contract. AI
                    explains the saved rule checks asynchronously; it cannot
                    invent an entry, change the stop or target, or block
                    delivery when unavailable.
                  </p>
                  <code>deepseek/deepseek-v4-pro-0813</code>
                </div>
                <span className="tag">Planned · Phase 9</span>
              </div>
              <div className="method-note">
                <strong>Calculation contract</strong>
                <p>
                  EMA uses an initial SMA seed. ATR uses Wilder smoothing,
                  seeded from 14 true ranges. Prices use Decimal arithmetic in
                  the backend engine; checkpointed state prevents reseeding
                  after a restart. Historical tests are available in Research;
                  reliable profitability has not been established.
                </p>
              </div>
            </>
          )}
          {page === "system" && (
            <>
              <div className="panel system-overview">
                <div>
                  <SectionLabel>LIVE OPERATIONS</SectionLabel>
                  <h2>Service status</h2>
                  <p>
                    Collector, engine and web delivery status are measured.
                    Telegram and AI review are later phases.
                  </p>
                </div>
                <button
                  className="secondary-button"
                  onClick={() => void refreshSystem()}
                >
                  <Activity size={15} />
                  Refresh status
                </button>
              </div>
              <div className="service-grid">
                {[
                  {
                    icon: Database,
                    title: "API & database",
                    status:
                      health === null
                        ? "Checking"
                        : connected
                          ? "Connected"
                          : "Offline",
                    text: connected
                      ? "Health check passed. Chosen-coin configuration can be saved."
                      : "Run the local FastAPI service and apply database migrations.",
                    good: connected,
                  },
                  {
                    icon: CandlestickChart,
                    title: "Binance collector",
                    status: health?.collector?.live
                      ? "Streaming"
                      : health?.collector?.state?.replaceAll("-", " ") ||
                        "Not running",
                    text: "500-bar warm-up per timeframe, completed candles, checkpoint recovery and REST gap repair.",
                    good: !!health?.collector?.live,
                  },
                  {
                    icon: Radio,
                    title: "Deterministic signal engine",
                    status: signalFeed.error
                      ? "Unavailable"
                      : engine?.state?.replaceAll("-", " ") || "Not running",
                    text: "New signals: 09:00 AM–11:00 PM IST. Market collection, expiry and source integrity monitoring continue around the clock.",
                    good: !!engine?.ready && !signalFeed.error,
                  },
                  {
                    icon: Bell,
                    title: "Web delivery",
                    status: health?.web_delivery?.state || "Not measured",
                    text: health?.web_delivery
                      ? health.web_delivery.backlog +
                        " events awaiting persistence. Delivery records survive restarts."
                      : "Start the web-delivery worker to persist committed events.",
                    good: health?.web_delivery?.state === "running",
                  },
                  {
                    icon: Database,
                    title: "Database backups",
                    status: health?.backup?.state || "Not measured",
                    text: "Daily PostgreSQL backups retain 14 days locally. Off-server copies are configured during VPS deployment.",
                    good: health?.backup?.state === "current",
                  },
                  {
                    icon: Send,
                    title: "Telegram delivery",
                    status:
                      health?.telegram?.replaceAll("-", " ") ||
                      "Not configured",
                    text:
                      health?.telegram_delivery &&
                      health.telegram !== "not-configured"
                        ? `${health.telegram_delivery.pending} queued · ${health.telegram_delivery.delivered} delivered · ${health.telegram_delivery.failed} failed · ${health.telegram_delivery.unknown} uncertain. Uncertain sends need review and are not automatically repeated.`
                        : "Server-only BotFather credentials and a verified destination chat are required.",
                    good:
                      health?.telegram === "running" &&
                      !health?.telegram_delivery?.failed &&
                      !health?.telegram_delivery?.unknown,
                  },
                  {
                    icon: Sparkles,
                    title: "DeepSeek evidence review",
                    status:
                      health?.ai?.replaceAll("-", " ") || "Not configured",
                    text:
                      health?.ai_review &&
                      health.ai_review.state !== "not-configured"
                        ? `${health.ai_review.pending} reviews pending · ${health.ai_review.daily_requests}/${health.ai_review.daily_limit} requests today. Commentary never changes signal levels.`
                        : "Server-only OpenRouter credentials, schema validation and spend controls.",
                    good: health?.ai === "running",
                  },
                  {
                    icon: ShieldCheck,
                    title: "Private user access",
                    status: authenticationRequired
                      ? "Invite only"
                      : "Local preview",
                    text: authenticationRequired
                      ? "Role permissions, expiring sessions and a durable audit trail."
                      : "Loopback development credentials; enable account authentication for hosting.",
                    good: authenticationRequired,
                  },
                ].map((s) => (
                  <section key={s.title} className="panel service-card">
                    <span className="service-icon">
                      <s.icon size={22} />
                    </span>
                    <h3>{s.title}</h3>
                    <span
                      className={`status-badge ${s.good ? "connected" : "expired"}`}
                    >
                      <i />
                      {s.status}
                    </span>
                    <p>{s.text}</p>
                  </section>
                ))}
              </div>
              <div className="info-card horizontal">
                <Workflow size={24} />
                <div>
                  <h3>Live signal operations</h3>
                  <p>
                    Paper observation is disabled by owner choice. Historical
                    comparisons and archived journals are retained. Website
                    events and Telegram report committed plans with fixed
                    levels. AI reviews evidence asynchronously. New signals run
                    from 09:00 AM to 11:00 PM IST; market collection stays
                    active.
                  </p>
                </div>
              </div>
            </>
          )}
          <footer className="workspace-footer">
            <span>
              <Mark small />
              MV Signal{" "}
              <span className="muted">· Private market workspace</span>
            </span>
            <span>
              Live operations v0.10.0 <i />
              {mode === "demo"
                ? "Synthetic preview"
                : engine?.ready && !signalFeed.error
                  ? engine.session?.open === false
                    ? "Session paused"
                    : "Engine running"
                  : "Engine waiting"}
            </span>
          </footer>
        </main>
      </div>
      <dialog
        ref={manageDialog}
        className="modal"
        aria-labelledby="manage-title"
      >
        <div className="modal-head">
          <div>
            <SectionLabel>YOUR UNIVERSE</SectionLabel>
            <h2 id="manage-title">Choose your markets</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close market settings"
            onClick={() => manageDialog.current?.close()}
          >
            <X size={20} />
          </button>
        </div>
        <p>
          Enter the USDT perpetual symbols you want to monitor. The collector
          validates contract metadata and warms up both timeframes before
          marking a coin ready.
        </p>
        <label className="form-label" htmlFor="chosen-coins">
          Chosen coins
        </label>
        <textarea
          id="chosen-coins"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          placeholder="BTCUSDT, ETHUSDT"
        />
        <small className="muted">
          Comma separated · 1–30 unique symbols · BTC and ETH have demo charts.
        </small>
        <div className="form-note">
          <Database size={16} />
          <span>
            {listLoaded
              ? "Changes are saved to the local database."
              : "Start the local API to save changes. The preview currently shows defaults."}
          </span>
        </div>
        {message && (
          <div className="form-error" role="alert">
            {message}
          </div>
        )}
        <div className="modal-actions">
          <button
            className="secondary-button"
            onClick={() => manageDialog.current?.close()}
          >
            Cancel
          </button>
          <button
            className="primary-button"
            disabled={saving}
            onClick={() => void saveWatchlist()}
          >
            {saving ? "Saving…" : "Save chosen coins"}
            <Check size={16} />
          </button>
        </div>
      </dialog>
      <dialog
        ref={detailDialog}
        className="modal detail-modal"
        aria-labelledby="detail-title"
      >
        <div className="modal-head">
          <div>
            <SectionLabel>ILLUSTRATIVE RECORD · {detailId}</SectionLabel>
            <h2 id="detail-title">
              {detailSymbol.replace("USDT", "")} / USDT{" "}
              <span className={`tag ${long ? "long-tag" : "short-tag"}`}>
                {long ? "Long" : "Short"}
              </span>
            </h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close setup details"
            onClick={() => detailDialog.current?.close()}
          >
            <X size={20} />
          </button>
        </div>
        <div className="detail-warning">
          Synthetic example for design review. Rule checks have not been
          evaluated by a live engine.
        </div>
        <div className="detail-levels">
          <div>
            <span>Entry reference</span>
            <strong>${money(entry)}</strong>
          </div>
          <div>
            <span>Stop · 2 ATR</span>
            <strong className="negative">${money(stop)}</strong>
          </div>
          <div>
            <span>Target · 2R</span>
            <strong className="positive">${money(target)}</strong>
          </div>
        </div>
        <h3>Required rule evidence</h3>
        <div className="evidence-list">
          {[
            "Completed 1H candle and aligned 4H confirmation",
            "EMA20 / EMA50 / SMA200 trend ordering",
            "Close-based EMA20 reclaim trigger",
            "Fresh entry quote and ≤ 0.5 ATR price drift",
            "No existing active setup for this symbol",
          ].map((e) => (
            <div key={e}>
              <span className="evidence-pending">
                <Clock3 size={14} />
              </span>
              <span>{e}</span>
              <small>Pending engine</small>
            </div>
          ))}
        </div>
        <div className="ai-preview">
          <Sparkles size={18} />
          <div>
            <strong>Evidence explanation</strong>
            <p>
              AI review will be attached to the persisted signal. The
              deterministic explanation remains available if AI is slow or
              unavailable.
            </p>
            <span className="tag">OpenRouter not connected</span>
          </div>
        </div>
        <p className="small-text muted">
          This preview has no exchange tick-size metadata; sample levels use
          cents. The production engine will use each contract’s validated
          filters.
        </p>
        <div className="modal-actions">
          <button
            className="secondary-button"
            onClick={() => detailDialog.current?.close()}
          >
            Close details
          </button>
        </div>
      </dialog>
      <dialog ref={helpDialog} className="modal" aria-labelledby="help-title">
        <div className="modal-head">
          <div>
            <SectionLabel>MV SIGNAL · V0.7</SectionLabel>
            <h2 id="help-title">Live operations & private access</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close preview information"
            onClick={() => helpDialog.current?.close()}
          >
            <X size={20} />
          </button>
        </div>
        <p>
          A working dashboard foundation for chosen-coin Binance futures
          signals. Binance charts show completed candles and backend-calculated
          indicators. Binance mode shows committed engine signals and evidence.
          Demo charts, journal records and setup examples are labeled as
          synthetic fixtures.
        </p>
        <p>
          The local API supports a migrated database, health checks, and saved
          chosen-coin configuration. Binance collection and Decimal indicators
          are implemented. The separate signal worker generates deterministic
          plans; held-position slots use operator reports. Historical backtests
          are separate, reproducible research experiments. Paper observation is
          disabled. The production package adds invite-only accounts, durable
          notifications, PostgreSQL and backups. Telegram and AI are connected
          during VPS deployment.
        </p>
        <p className="small-text">
          TradingView Lightweight Charts™ · Copyright (с) 2025 TradingView, Inc.{" "}
          <a
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noreferrer"
          >
            TradingView chart credits
          </a>
          .
        </p>
        <div className="modal-actions">
          <button
            className="primary-button"
            onClick={() => {
              helpDialog.current?.close();
              navigate("system");
            }}
          >
            View build status
            <ArrowRight size={16} />
          </button>
        </div>
      </dialog>
    </div>
  );
}
