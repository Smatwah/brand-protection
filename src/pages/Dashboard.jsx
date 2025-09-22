import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ReportModal from "../components/ReportModal.jsx";
import ScreenshotModal from "../components/ScreenshotModal.jsx";
import { apiUrl, resolveAssetUrl } from "../lib/api.js";

const emptySnapshot = {
  summary: {
      totalMonitored: 0,
      totalDetected: 0,
      totalDetections: 0,
      highRisk: 0,
      mediumRisk: 0,
      lowRisk: 0,
      unknownRisk: 0,
      brandsImpersonated: 0,
      lastDetectionMinutesAgo: null,
      lastDetectionAt: null,
    },
  riskDistribution: [],
  timeline: [],
  recentDetections: [],
  detectionsByRiskLevel: [],
};

function normaliseRiskScore(value) {
  if (typeof value !== "number") {
    const numeric = Number.parseFloat(value);
    if (Number.isFinite(numeric)) value = numeric;
  }
  if (!Number.isFinite(value)) return null;
  if (value <= 1) return Math.round(value * 100);
  return Math.round(value);
}

function normaliseRiskLevel(value) {
  if (!value || typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
}

function normaliseSnapshot(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const summarySource = payload.summary ?? payload;
  const tableSource = payload.recentDetections ?? payload.recent_detections ?? payload.table ?? [];
  const riskDistributionSource = payload.riskDistribution ?? payload.risk_distribution ?? [];
  const timelineSource = payload.timeline ?? payload.detections_over_time ?? [];
  const byRiskSource = payload.detectionsByRiskLevel ?? payload.detections_by_risk_level ?? [];

  const totalDetectedRaw = Number(
    summarySource.totalDetected ??
    summarySource.totalDetections ??
    summarySource.detected ??
    summarySource.total ??
    0
  );
  const totalMonitoredRaw = Number(
    summarySource.totalMonitored ??
    summarySource.monitored ??
    summarySource.total_monitored ??
    0
  );
  const totalDetected = Number.isFinite(totalDetectedRaw) ? totalDetectedRaw : 0;
  const totalMonitored = Number.isFinite(totalMonitoredRaw) ? totalMonitoredRaw : 0;
  const unknownRiskRaw = Number(summarySource.unknownRisk ?? summarySource.unknown_risk ?? 0);
  const unknownRisk = Number.isFinite(unknownRiskRaw) ? unknownRiskRaw : 0;
  return {
    summary: {
      totalDetected,
      totalDetections: totalDetected,
      totalMonitored,
      highRisk: summarySource.highRisk ?? summarySource.high_risk ?? 0,
      mediumRisk: summarySource.mediumRisk ?? summarySource.medium_risk ?? 0,
      lowRisk: summarySource.lowRisk ?? summarySource.low_risk ?? 0,
      unknownRisk,
      brandsImpersonated: summarySource.brandsImpersonated ?? summarySource.unique_brands ?? 0,
      lastDetectionMinutesAgo: summarySource.lastDetectionMinutesAgo ?? summarySource.last_detection_minutes ?? null,
      lastDetectionAt: summarySource.lastDetectionAt ?? summarySource.last_detection_at ?? null,
    },
    riskDistribution: Array.isArray(riskDistributionSource)
      ? riskDistributionSource.map((item) => ({
          label: item.label ?? item.name ?? "Unknown",
          value: item.value ?? item.count ?? 0,
        }))
      : [],
    detectionsByRiskLevel: Array.isArray(byRiskSource)
      ? byRiskSource.map((item) => ({
          label: item.label ?? item.name ?? "Unknown",
          value: item.value ?? item.count ?? 0,
        }))
      : [],
    timeline: Array.isArray(timelineSource)
      ? timelineSource.map((item, index) => {
          const detectedRaw = Number(item.detected ?? item.detections ?? item.count ?? 0);
          const monitoredRaw = Number(item.monitored ?? 0);
          const detected = Number.isFinite(detectedRaw) ? detectedRaw : 0;
          const monitored = Number.isFinite(monitoredRaw) ? monitoredRaw : 0;
          const totalRaw = Number(item.total ?? detected + monitored);
          const total = Number.isFinite(totalRaw) ? totalRaw : detected + monitored;
          return {
            time: item.time ?? item.label ?? `T${index + 1}`,
            timestamp: item.timestamp ?? item.iso ?? null,
            detected,
            monitored,
            total,
            detections: detected,
          };
        })
      : [],
    recentDetections: Array.isArray(tableSource)
      ? tableSource.map((row, index) => ({
          id: String(row.id ?? row.url ?? `row-${index}`),
          brand: row.brand ?? row.brand_name ?? "Unknown brand",
          detectedAt: row.detectedAt ?? row.detected_at ?? row.timestamp ?? null,
          riskScore: normaliseRiskScore(row.riskScore ?? row.risk_score),
          riskLevel: normaliseRiskLevel(row.riskLevel ?? row.risk_level),
          url: row.url ?? row.full_url ?? null,
          description: row.description ?? row.summary ?? null,
          recommendation: row.recommendation ?? null,
          screenshotPath: resolveAssetUrl(row.screenshot_path ?? row.screenshotPath ?? null),
        }))
      : [],
  };
}

async function requestDashboardSnapshot(signal, endpoint) {
  const response = await fetch(endpoint, { signal });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  return normaliseSnapshot(payload);
}

function formatTimeAgo(date) {
  if (!date) return "N/A";
  const diffMs = Date.now() - new Date(date).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return "N/A";
  if (minutes === 0) return "moments ago";
  if (minutes === 1) return "1 minute ago";
  return `${minutes} minutes ago`;
}

function formatDateTime(date) {
  if (!date) return "N/A";
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "N/A";
  return parsed.toLocaleString();
}

const riskColors = {
  High: "#f87171",
  Medium: "#facc15",
  Low: "#34d399",
  Unknown: "#64748b",
};

function DashboardPage() {
  const summaryEndpoint = useMemo(() => apiUrl("/api/url-detection/summary"), []);

  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedDetection, setSelectedDetection] = useState(null);
  const [screenshotDetection, setScreenshotDetection] = useState(null);

  const fetchSnapshot = async ({ manual = false } = {}) => {
    const controller = new AbortController();
    const { signal } = controller;

    if (manual) {
      setIsLoading(true);
      setError(null);
    }

    try {
      const data = await requestDashboardSnapshot(signal, summaryEndpoint);
      if (data) {
        setSnapshot(data);
        if (manual) {
          setError(null);
        }
      } else if (manual) {
        setSnapshot(emptySnapshot);
        setError("Waiting for detections. Refresh once new data is available.");
      }
    } catch (error) {
      console.error('Failed to refresh dashboard snapshot', error);
      if (manual) {
        setError(`Unable to refresh dashboard data from ${summaryEndpoint} right now. Please try again in a moment.`);
      }
    } finally {
      if (manual) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      try {
        const controller = new AbortController();
        const data = await requestDashboardSnapshot(controller.signal, summaryEndpoint);
        if (!isMounted) return;
        if (data) {
          setSnapshot(data);
          setError(null);
        } else {
          setSnapshot(emptySnapshot);
        }
      } catch (error) {
        if (!isMounted) return;
        console.error('Failed to load dashboard snapshot', error);
        setError("Waiting for the backend to publish dashboard metrics.");
      }
    };

    load();
    const interval = setInterval(load, 15000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [summaryEndpoint]);

  const lastDetectionAt = snapshot.summary.lastDetectionAt ?? snapshot.recentDetections?.[0]?.detectedAt ?? null;

  const summaryCards = useMemo(
    () => [
      {
        label: "Monitored",
        value: snapshot.summary.totalMonitored,
        helper: "Active watchlist items",
      },
      {
        label: "Detected",
        value: snapshot.summary.totalDetected,
        helper: "Alerts raised in the current window",
      },
      {
        label: "High risk",
        value: snapshot.summary.highRisk,
        helper: "Score above 75%",
      },
      {
        label: "Brands impersonated",
        value: snapshot.summary.brandsImpersonated,
        helper: "Unique brand mentions",
      },
      {
        label: "Last detection",
        value: formatDateTime(lastDetectionAt),
        helper: lastDetectionAt ? formatTimeAgo(lastDetectionAt) : "No detections yet",
      },
    ],
    [snapshot, lastDetectionAt]
  );

  const riskMix = snapshot.detectionsByRiskLevel.length ? snapshot.detectionsByRiskLevel : snapshot.riskDistribution;
  const trimmedTimeline = useMemo(() => snapshot.timeline.slice(-48), [snapshot.timeline]);

  const velocitySummary = useMemo(() => {
    if (!trimmedTimeline.length) return null;
    const [firstPoint] = trimmedTimeline;
    let detectedTotal = 0;
    let monitoredTotal = 0;
    let peakDetectedPoint = firstPoint;
    let peakMonitoredPoint = firstPoint;

    for (const point of trimmedTimeline) {
      const detectedValue = Number(point.detected ?? point.detections ?? 0);
      const monitoredValue = Number(point.monitored ?? 0);
      const detectedCount = Number.isFinite(detectedValue) ? detectedValue : 0;
      const monitoredCount = Number.isFinite(monitoredValue) ? monitoredValue : 0;
      detectedTotal += detectedCount;
      monitoredTotal += monitoredCount;

      if (!peakDetectedPoint || detectedCount >= Number(peakDetectedPoint?.detected ?? peakDetectedPoint?.detections ?? 0)) {
        peakDetectedPoint = point;
      }
      if (!peakMonitoredPoint || monitoredCount >= Number(peakMonitoredPoint?.monitored ?? 0)) {
        peakMonitoredPoint = point;
      }
    }

    const latest = trimmedTimeline[trimmedTimeline.length - 1];
    return {
      detectedAverage: detectedTotal / trimmedTimeline.length,
      monitoredAverage: monitoredTotal / trimmedTimeline.length,
      peakDetectedPoint,
      peakMonitoredPoint,
      detectedTotal,
      monitoredTotal,
      latest,
    };
  }, [trimmedTimeline]);

  const sparklineData = useMemo(() => snapshot.timeline.slice(-12), [snapshot.timeline]);
  const formatTimelinePointLabel = (point) => {
    if (!point) return "--";
    if (point.timestamp) {
      const parsed = new Date(point.timestamp);
      if (!Number.isNaN(parsed.getTime())) {
        return parsed.toLocaleString();
      }
    }
    return point.time ?? "--";
  };

  const totalDetected = snapshot.summary.totalDetected || snapshot.summary.totalDetections || 0;
  const highRiskShare = totalDetected ? Math.round((snapshot.summary.highRisk / totalDetected) * 100) : 0;
  const peakDetectedCount = velocitySummary?.peakDetectedPoint
    ? Number(velocitySummary.peakDetectedPoint.detected ?? velocitySummary.peakDetectedPoint.detections ?? 0)
    : 0;
  const peakMonitoredCount = velocitySummary?.peakMonitoredPoint
    ? Number(velocitySummary.peakMonitoredPoint.monitored ?? 0)
    : 0;
  const latestDetectedCount = velocitySummary?.latest
    ? Number(velocitySummary.latest.detected ?? velocitySummary.latest.detections ?? 0)
    : 0;
  const latestMonitoredCount = velocitySummary?.latest
    ? Number(velocitySummary.latest.monitored ?? 0)
    : 0;

  const tableRows = snapshot.recentDetections ?? [];

  return (
    <section className="space-y-10">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.4em] text-slate-400">Overview</p>
          <h2 className="text-3xl font-semibold text-white">Threat monitoring dashboard</h2>
        </div>
        <div className="flex items-center gap-3">
          {error && <span className="text-sm text-warning-400">{error}</span>}
          <button
            type="button"
            onClick={() => fetchSnapshot({ manual: true })}
            className="rounded-full bg-accent-500 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-accent-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
          >
            {isLoading ? "Refreshing..." : "Refresh data"}
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        {summaryCards.map((card) => (
          <div key={card.label} className="glass rounded-3xl p-5 shadow-card">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-400">{card.label}</p>
            <p className="mt-3 text-3xl font-semibold text-white">{card.value}</p>
            <p className="mt-2 text-xs text-slate-400">{card.helper}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="glass rounded-3xl p-6 shadow-card xl:col-span-2">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-white">Recent detection velocity</h3>
            <span className="text-xs text-slate-400">Last {trimmedTimeline.length || "-"} intervals</span>
          </div>
          <div className="mt-4 h-72">
            {trimmedTimeline.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trimmedTimeline}>
                  <defs>
                    <linearGradient id="detectedGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.8} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="monitoredGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#a855f7" stopOpacity={0.45} />
                      <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" stroke="#94a3b8" tickLine={false} axisLine={{ stroke: "#1f2937" }} />
                  <YAxis stroke="#94a3b8" tickLine={false} axisLine={{ stroke: "#1f2937" }} allowDecimals={false} />
                  <Tooltip
                    formatter={(value, name) => {
                      if (typeof value !== "number") return [value, name];
                      if (name === "detected" || name === "detections") return [value, "Detected"];
                      if (name === "monitored") return [value, "Monitored"];
                      return [value, name];
                    }}
                    labelFormatter={(_, payload) => formatTimelinePointLabel(payload?.[0]?.payload)}
                    contentStyle={{
                      backgroundColor: "rgba(15,23,42,0.9)",
                      borderRadius: "1rem",
                      border: "1px solid rgba(148,163,184,0.1)",
                    }}
                    labelStyle={{ color: "#e2e8f0" }}
                  />
                  <Legend
                    verticalAlign="top"
                    height={32}
                    iconType="circle"
                    formatter={(value) => {
                      if (value === "detected" || value === "detections") return "Detected";
                      if (value === "monitored") return "Monitored";
                      return value;
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="monitored"
                    stroke="#a855f7"
                    strokeWidth={2}
                    fill="url(#monitoredGradient)"
                    fillOpacity={0.35}
                    activeDot={{ r: 4 }}
                    name="monitored"
                  />
                  <Area
                    type="monotone"
                    dataKey="detected"
                    stroke="#38bdf8"
                    strokeWidth={3}
                    fill="url(#detectedGradient)"
                    activeDot={{ r: 5 }}
                    name="detected"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Activity will appear once detections stream in.
              </div>
            )}
          </div>
          {velocitySummary && (
            <div className="mt-4 grid gap-4 border-t border-white/5 pt-4 text-sm text-slate-300 sm:grid-cols-3">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Average per interval</p>
                <p className="mt-1 text-lg font-semibold text-white">
                  {velocitySummary.detectedAverage.toFixed(1)}
                  <span className="ml-2 text-xs text-slate-400">detected</span>
                </p>
                <p className="text-xs text-slate-500">Monitored: {velocitySummary.monitoredAverage.toFixed(1)}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Peak interval</p>
                <p className="mt-1 text-lg font-semibold text-white">{peakDetectedCount}</p>
                <p className="text-xs text-slate-500">{formatTimelinePointLabel(velocitySummary.peakDetectedPoint)}</p>
                <p className="mt-2 text-xs text-slate-500">Monitored: {peakMonitoredCount} ({formatTimelinePointLabel(velocitySummary.peakMonitoredPoint)})</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Latest interval</p>
                <p className="mt-1 text-lg font-semibold text-white">{latestDetectedCount}</p>
                <p className="text-xs text-slate-500">Monitored: {latestMonitoredCount}</p>
                <p className="text-xs text-slate-500">{formatTimelinePointLabel(velocitySummary.latest)}</p>
              </div>
            </div>
          )}
        </div>

        <div className="glass rounded-3xl p-6 shadow-card">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-white">Risk score mix</h3>
            <span className="text-xs text-slate-400">Rolling window</span>
          </div>
          <div className="mt-4 h-72">
            {riskMix.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={riskMix} innerRadius={65} outerRadius={100} paddingAngle={4} dataKey="value">
                    {riskMix.map((entry) => (
                      <Cell key={entry.label} fill={riskColors[entry.label] ?? "#38bdf8"} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [`${value}`, name]}
                    contentStyle={{
                      backgroundColor: "rgba(15,23,42,0.9)",
                      borderRadius: "1rem",
                      border: "1px solid rgba(148,163,184,0.1)",
                    }}
                    labelStyle={{ color: "#e2e8f0" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Risk distribution will appear when detections arrive.
              </div>
            )}
          </div>
          <div className="mt-4 space-y-2 text-sm text-slate-300">
            {riskMix.map((entry) => (
              <div key={entry.label} className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: riskColors[entry.label] ?? "#38bdf8" }} />
                  {entry.label}
                </span>
                <span>{entry.value}</span>
              </div>
            ))}
            {!riskMix.length && <span className="text-xs text-slate-500">No data available yet.</span>}
          </div>
        </div>
      </div>

      <div className="glass rounded-3xl p-6 shadow-card">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">Detection service health</h3>
            <p className="text-sm text-slate-400">Operational insights derived from the current stream.</p>
          </div>
          <div className="h-16 w-full md:w-48">
            {sparklineData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparklineData} margin={{ left: 0, right: 0, top: 10, bottom: 0 }}>
                  <Line type="monotone" dataKey="detected" stroke="#60a5fa" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="monitored" stroke="#a855f7" strokeDasharray="4 4" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-slate-500">No samples</div>
            )}
          </div>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-4 text-sm text-slate-300">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">High risk share</p>
            <p className="mt-1 text-lg font-semibold text-white">{totalDetected ? `${highRiskShare}%` : "-"}</p>
            <p className="text-xs text-slate-500">of all detections</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Medium risk</p>
            <p className="mt-1 text-lg font-semibold text-white">{snapshot.summary.mediumRisk}</p>
            <p className="text-xs text-slate-500">Score 26-75%</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Low risk</p>
            <p className="mt-1 text-lg font-semibold text-white">{snapshot.summary.lowRisk}</p>
            <p className="text-xs text-slate-500">Under watch</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Last detection</p>
            <p className="mt-1 text-lg font-semibold text-white">{formatTimeAgo(lastDetectionAt)}</p>
            <p className="text-xs text-slate-500">{formatDateTime(lastDetectionAt)}</p>
          </div>
        </div>
      </div>

      <div className="glass rounded-3xl p-6 shadow-card">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Recent detections</h3>
          <span className="text-xs text-slate-400">Interact with any row to review evidence</span>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="text-left text-xs uppercase tracking-[0.3em] text-slate-400">
              <tr>
                <th className="py-3 pr-6">Brand</th>
                <th className="py-3 pr-6">Detection date</th>
                <th className="py-3 pr-6">Risk score</th>
                <th className="py-3 pr-6">Screenshot</th>
                <th className="py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-slate-200">
              {tableRows.map((row) => (
                <tr key={row.id} className="hover:bg-white/5">
                  <td className="py-3 pr-6 font-medium">{row.brand}</td>
                  <td className="py-3 pr-6 text-slate-300">
                    {row.detectedAt ? formatDateTime(row.detectedAt) : "N/A"}
                  </td>
                  <td className="py-3 pr-6">
                    <span className="inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-semibold">
                      <span className="text-accent-400">
                        {row.riskScore != null ? `${row.riskScore}%` : "Pending analysis"}
                      </span>
                      <span className="text-slate-400">{row.riskLevel ?? "Pending"}</span>
                    </span>
                  </td>
                  <td className="py-3 pr-6">
                    <button
                      type="button"
                      onClick={() => setScreenshotDetection(row)}
                      disabled={!row.screenshotPath}
                      className={`rounded-full px-4 py-2 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
                        row.screenshotPath
                          ? "border border-white/20 text-slate-100 hover:bg-white/10"
                          : "border border-white/10 text-slate-500 cursor-not-allowed"
                      }`}
                    >
                      View
                    </button>
                  </td>
                  <td className="py-3">
                    <button
                      type="button"
                      onClick={() => setSelectedDetection(row)}
                      className="rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                    >
                      View report
                    </button>
                  </td>
                </tr>
              ))}
              {!tableRows.length && (
                <tr>
                  <td colSpan="5" className="py-6 text-center text-sm text-slate-400">
                    Waiting for detections. The backend will populate this table when new alerts are available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedDetection && (
        <ReportModal detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}

      {screenshotDetection?.screenshotPath && (
        <ScreenshotModal detection={screenshotDetection} onClose={() => setScreenshotDetection(null)} />
      )}
    </section>
  );
}

export default DashboardPage;




































