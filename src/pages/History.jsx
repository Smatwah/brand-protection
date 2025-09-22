import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ArrowPathIcon,
  ArrowUpOnSquareIcon,
  DocumentArrowDownIcon,
  PhotoIcon,
  FlagIcon,
  LinkIcon,
} from "@heroicons/react/24/outline";

import ScreenshotModal from "../components/ScreenshotModal.jsx";

import EscalationModal from "../components/EscalationModal.jsx";

import UrlPreviewModal from "../components/UrlPreviewModal.jsx";

import { apiUrl, resolveAssetUrl } from "../lib/api.js";

import { copyTextToClipboard } from "../lib/clipboard.js";

import {
  buildEscalationEvidence,
  extractEmails,
  findInvalidEmails,
  loadStoredEscalationEmails,
  saveStoredEscalationEmails,
} from "../lib/escalation.js";

const RISK_LEVEL_OPTIONS = ["High", "Medium", "Low", "Unknown"];

const HISTORY_LIMIT = 500;

const URL_PREVIEW_MODE = "modal";
// Set to "inline" to expand the URL within table rows.

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
  if (!value || typeof value !== "string") return "Unknown";

  const trimmed = value.trim();

  if (!trimmed) return "Unknown";

  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
}

function truncateUrl(url, limit = 64) {
  if (!url || typeof url !== "string") return "";

  if (url.length <= limit) return url;

  return `${url.slice(0, limit - 3)}...`;
}

function normaliseHistoryDetection(item, index) {
  if (!item) return null;

  const riskScore = normaliseRiskScore(item.risk_score ?? item.riskScore);

  const riskLevel = normaliseRiskLevel(item.risk_level ?? item.riskLevel);

  const screenshotPath = resolveAssetUrl(
    item.screenshot_path ?? item.screenshotPath ?? item.screenshot ?? null,
  );

  const actionsTaken =
    item.actions_taken ??
    item.actionsTaken ??
    item.recommendation ??
    "Pending review";

  return {
    id: String(item.id ?? item.url ?? `history-${index}`),

    brand: item.brand ?? item.brand_name ?? "Unknown brand",

    riskScore,

    riskLevel,

    detectedAt: item.detected_at ?? item.detectedAt ?? item.timestamp ?? null,

    url: item.url ?? item.full_url ?? "",

    actionsTaken,

    description: item.description ?? item.summary ?? "",

    recommendation: item.recommendation ?? null,

    screenshotPath,
  };
}

function HistoryPage() {
  const [history, setHistory] = useState([]);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState(null);

  const [search, setSearch] = useState("");

  const [selectedRisks, setSelectedRisks] = useState(
    new Set(RISK_LEVEL_OPTIONS),
  );

  const [screenshotDetection, setScreenshotDetection] = useState(null);

  const [actionFeedback, setActionFeedback] = useState(null);

  const [escalationTarget, setEscalationTarget] = useState(null);

  const [escalationSubmitting, setEscalationSubmitting] = useState(false);

  const [escalationError, setEscalationError] = useState(null);

  const [lastEscalationEmails, setLastEscalationEmails] = useState(() =>
    loadStoredEscalationEmails(),
  );

  const [toastMessage, setToastMessage] = useState(null);

  const [urlPreviewTarget, setUrlPreviewTarget] = useState(null);
  const [expandedUrlRowId, setExpandedUrlRowId] = useState(null);
  const [inlineUrlFeedback, setInlineUrlFeedback] = useState({
    id: null,
    state: "idle",
  });

  const isInlineUrlPreview = URL_PREVIEW_MODE === "inline";

  const escalationEndpoint = useMemo(
    () => apiUrl("/api/url-detection/escalate"),
    [],
  );

  useEffect(() => {
    let ignore = false;

    const fetchHistory = async () => {
      setLoading(true);

      setError(null);

      try {
        const baseUrl = apiUrl("/api/url-detection/history");

        const limitParam = String(HISTORY_LIMIT);

        let requestUrl = baseUrl;

        if (typeof window !== "undefined") {
          try {
            const url = new URL(baseUrl, window.location.origin);

            url.searchParams.set("limit", limitParam);

            requestUrl = url.toString();
          } catch {
            const joiner = baseUrl.includes("?") ? "&" : "?";

            requestUrl = `${baseUrl}${joiner}limit=${encodeURIComponent(limitParam)}`;
          }
        } else {
          const joiner = baseUrl.includes("?") ? "&" : "?";

          requestUrl = `${baseUrl}${joiner}limit=${encodeURIComponent(limitParam)}`;
        }

        const response = await fetch(requestUrl);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const payload = await response.json();

        const rawItems = Array.isArray(payload?.items)
          ? payload.items
          : Array.isArray(payload)
            ? payload
            : [];

        const normalised = rawItems

          .map((item, index) => normaliseHistoryDetection(item, index))

          .filter(Boolean)

          .sort(
            (a, b) =>
              new Date(b.detectedAt ?? 0).getTime() -
              new Date(a.detectedAt ?? 0).getTime(),
          );

        if (!ignore) {
          setHistory(normalised);
        }
      } catch (fetchError) {
        console.error("Failed to load history", fetchError);

        if (!ignore) {
          setError(
            "We couldn't load historical detections right now. Try refreshing.",
          );
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    fetchHistory();

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!actionFeedback) return;

    const timer = setTimeout(() => setActionFeedback(null), 4000);

    return () => clearTimeout(timer);
  }, [actionFeedback]);

  useEffect(() => {
    if (!toastMessage) return;

    const timer = setTimeout(() => setToastMessage(null), 4000);

    return () => clearTimeout(timer);
  }, [toastMessage]);

  useEffect(() => {
    if (!isInlineUrlPreview) return undefined;
    if (!inlineUrlFeedback.id || inlineUrlFeedback.state === "idle") {
      return undefined;
    }

    const timer = setTimeout(
      () => setInlineUrlFeedback({ id: null, state: "idle" }),
      2500,
    );

    return () => clearTimeout(timer);
  }, [inlineUrlFeedback, isInlineUrlPreview]);

  const filteredHistory = useMemo(() => {
    const activeRisks = selectedRisks.size
      ? selectedRisks
      : new Set(RISK_LEVEL_OPTIONS);

    const needle = search.trim().toLowerCase();

    return history.filter((item) => {
      if (!activeRisks.has(item.riskLevel ?? "Unknown")) return false;

      if (!needle) return true;

      const haystack = [
        item.brand,
        item.url,
        item.description,
        item.actionsTaken,
      ]

        .filter(Boolean)

        .join(" ")

        .toLowerCase();

      return haystack.includes(needle);
    });
  }, [history, search, selectedRisks]);

  const hasActiveFilters = useMemo(() => {
    if (search.trim()) return true;

    return selectedRisks.size < RISK_LEVEL_OPTIONS.length;
  }, [search, selectedRisks]);

  const emptyStateMessage = useMemo(() => {
    if (loading) return "Loading detections.";

    if (error) return error;

    if (hasActiveFilters) return "No detections match the current filters.";

    return "No historical detections yet. New detections will appear here once processed.";
  }, [loading, error, hasActiveFilters]);

  const handleRiskToggle = (level) => {
    setSelectedRisks((current) => {
      const next = new Set(current);

      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }

      if (next.size === 0) {
        return new Set(RISK_LEVEL_OPTIONS);
      }

      return next;
    });
  };

  const handleExportCsv = () => {
    const rows = [
      [
        "Timestamp",
        "Brand",
        "Risk Score",
        "Risk Level",
        "URL",
        "Actions Taken",
      ],

      ...filteredHistory.map((item) => [
        item.detectedAt ? new Date(item.detectedAt).toISOString() : "",

        item.brand,

        item.riskScore != null ? `${item.riskScore}%` : "",

        item.riskLevel ?? "Unknown",

        item.url ?? "",

        item.actionsTaken ?? "",
      ]),
    ];

    const csvContent = rows

      .map((row) =>
        row

          .map((value) => '"' + String(value ?? "").replace(/"/g, '""') + '"')

          .join(","),
      )

      .join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });

    const link = document.createElement("a");

    link.href = URL.createObjectURL(blob);

    link.download = "detection-history.csv";

    document.body.appendChild(link);

    link.click();

    document.body.removeChild(link);
  };

  const handleExportPdf = () => {
    const htmlRows = filteredHistory

      .map((item) => {
        const timestamp = item.detectedAt
          ? new Date(item.detectedAt).toLocaleString()
          : "";

        const riskDisplay = `${item.riskScore != null ? `${item.riskScore}%` : ""} (${item.riskLevel ?? "Unknown"})`;

        const urlDisplay = item.url ? truncateUrl(item.url, 60) : "";

        const actionsDisplay = item.actionsTaken ?? "";

        return `

          <tr>

            <td>${timestamp}</td>

            <td>${item.brand}</td>

            <td>${riskDisplay}</td>

            <td>${urlDisplay}</td>

            <td>${actionsDisplay}</td>

          </tr>

        `;
      })

      .join("\n");

    const html = `<!DOCTYPE html>

<html>

<head>

  <meta charset="utf-8" />

  <title>Detection History Export</title>

  <style>

    body { font-family: Arial, sans-serif; color: #111827; padding: 24px; }

    h1 { font-size: 20px; margin-bottom: 16px; }

    table { width: 100%; border-collapse: collapse; font-size: 12px; }

    th, td { border: 1px solid #cbd5f5; padding: 8px; text-align: left; }

    th { background: #e2e8f0; text-transform: uppercase; letter-spacing: 0.08em; font-size: 11px; }

  </style>

</head>

<body>

  <h1>Detection History Export</h1>

  <table>

    <thead>

      <tr>

        <th>Timestamp</th>

        <th>Brand</th>

        <th>Risk</th>

        <th>URL</th>

        <th>Actions Taken</th>

      </tr>

    </thead>

    <tbody>

      ${htmlRows}

    </tbody>

  </table>

</body>

</html>`;

    const printWindow = window.open("", "_blank", "noopener,noreferrer");

    if (printWindow) {
      printWindow.document.write(html);

      printWindow.document.close();

      printWindow.focus();

      printWindow.print();
    }
  };

  const handleEscalationSubmit = useCallback(
    async (input) => {
      if (!escalationTarget) return;

      const trimmed = input.trim();

      const emails = extractEmails(trimmed);

      if (!emails.length) {
        setEscalationError("Enter at least one recipient email address.");

        return;
      }

      const invalid = findInvalidEmails(emails);

      if (invalid.length) {
        setEscalationError(`Please double-check: ${invalid.join(", ")}`);

        return;
      }

      setEscalationSubmitting(true);

      setEscalationError(null);

      try {
        const detectionId =
          escalationTarget.id ?? escalationTarget.detectionId ?? "";
        if (!detectionId) {
          setEscalationError("We couldn't find a detection ID for this item.");
          return;
        }

        const evidence = buildEscalationEvidence(escalationTarget);

        const requestBody = {
          detection_id: String(detectionId),

          emails,
        };

        if (evidence) {
          requestBody.evidence = evidence;
        }

        const response = await fetch(escalationEndpoint, {
          method: "POST",

          headers: { "Content-Type": "application/json" },

          body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
          const responseText = await response.text().catch(() => "");
          let detailMessage =
            "We couldn't send the escalation. Please try again.";
          let parsed;
          if (responseText) {
            try {
              parsed = JSON.parse(responseText);
            } catch {
              parsed = responseText;
            }
          }
          if (parsed) {
            if (typeof parsed === "string" && parsed.trim()) {
              detailMessage = parsed.trim();
            } else if (typeof parsed === "object") {
              const detail =
                parsed.detail ?? parsed.message ?? parsed.error ?? null;
              if (typeof detail === "string" && detail.trim()) {
                detailMessage = detail.trim();
              }
            }
          }
          setEscalationError(detailMessage);
          return;
        }

        let payload = {};

        try {
          payload = await response.json();
        } catch {
          payload = {};
        }

        const sentTo =
          Array.isArray(payload?.sent_to) && payload.sent_to.length
            ? payload.sent_to
            : emails;

        const storedValue = emails.join(", ");

        saveStoredEscalationEmails(storedValue);

        setLastEscalationEmails(storedValue);

        setEscalationTarget(null);

        setToastMessage(`Escalation sent to ${sentTo.join(", ")}`);
      } catch (error) {
        console.error("Escalation request failed", error);

        setEscalationError(
          "We couldn't send the escalation. Please try again.",
        );
      } finally {
        setEscalationSubmitting(false);
      }
    },

    [escalationEndpoint, escalationTarget],
  );

  const handleEscalationCancel = useCallback(() => {
    if (escalationSubmitting) return;

    setEscalationTarget(null);

    setEscalationError(null);
  }, [escalationSubmitting]);

  const handleEscalationEmailsChange = useCallback(() => {
    if (escalationError) {
      setEscalationError(null);
    }
  }, [escalationError]);

  const handleUrlPreviewClick = useCallback(
    (detection) => {
      if (!detection || !detection.url) return;

      if (isInlineUrlPreview) {
        setExpandedUrlRowId((previous) =>
          previous === detection.id ? null : detection.id,
        );
        setInlineUrlFeedback({ id: null, state: "idle" });
        return;
      }

      setUrlPreviewTarget(detection);
    },
    [isInlineUrlPreview],
  );

  const handleInlineCopy = useCallback(async (detection) => {
    if (!detection || !detection.url) return;

    const copied = await copyTextToClipboard(detection.url);
    setInlineUrlFeedback({
      id: detection.id,
      state: copied ? "success" : "error",
    });
  }, []);

  const handleInlineOpen = useCallback((detection) => {
    if (!detection || !detection.url) return;
    if (typeof window === "undefined") return;

    const confirmOpen = window.confirm(
      "Opening this URL will launch a new browser tab. Only proceed if you trust the destination.",
    );

    if (!confirmOpen) return;

    window.open(detection.url, "_blank", "noopener,noreferrer");
  }, []);

  const closeUrlPreviewModal = useCallback(() => {
    setUrlPreviewTarget(null);
  }, []);

  const handleQuickAction = (action, detection) => {
    if (!detection) return;

    if (action === "escalate") {
      setEscalationTarget({
        ...detection,

        report:
          detection.report ??
          detection.description ??
          detection.actionsTaken ??
          detection.recommendation ??
          null,
      });

      setEscalationError(null);

      return;
    }

    setActionFeedback(`Flagged as false positive for ${detection.brand}.`);
  };

  return (
    <div className="space-y-8">
      {toastMessage && (
        <div className="fixed inset-x-0 top-6 z-40 flex justify-center px-4">
          <div className="max-w-xl rounded-full border border-success-400/40 bg-success-500/10 px-5 py-3 text-sm font-medium text-success-200 shadow-lg">
            {toastMessage}
          </div>
        </div>
      )}

      <header className="flex flex-col gap-4 border-b border-white/10 pb-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.4em] text-slate-400">
            Detection archive
          </p>

          <h1 className="text-3xl font-semibold text-white">History</h1>

          <p className="mt-2 text-sm text-slate-400">
            Explore detections beyond the real-time window, filter by risk
            level, and export reports for downstream analysis.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            <ArrowPathIcon className="h-4 w-4" />
            Refresh
          </button>

          <button
            type="button"
            onClick={handleExportCsv}
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            <DocumentArrowDownIcon className="h-4 w-4" />
            Export CSV
          </button>

          <button
            type="button"
            onClick={handleExportPdf}
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            <DocumentArrowDownIcon className="h-4 w-4 rotate-90" />
            Export PDF
          </button>
        </div>
      </header>

      <section className="glass rounded-3xl p-6 shadow-card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center">
            <div className="flex-1">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Search
              </label>

              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search brand, URL, or notes"
                className="mt-2 w-full rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:border-accent-400 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
              />
            </div>

            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Risk level
              </p>

              <div className="mt-2 flex flex-wrap gap-2">
                {RISK_LEVEL_OPTIONS.map((level) => {
                  const active = selectedRisks.has(level);

                  return (
                    <button
                      key={level}
                      type="button"
                      onClick={() => handleRiskToggle(level)}
                      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                        active
                          ? "border border-accent-400 bg-accent-400/20 text-accent-200"
                          : "border border-white/15 text-slate-400 hover:border-accent-400/60 hover:text-accent-200"
                      }`}
                    >
                      {level}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {actionFeedback && (
          <div className="mt-4 rounded-2xl border border-success-400/30 bg-success-400/10 p-4 text-xs text-success-200">
            {actionFeedback}
          </div>
        )}

        <div className="mt-6 overflow-x-auto">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="text-left text-xs uppercase tracking-[0.3em] text-slate-400">
              <tr>
                <th className="py-3 pr-6">Timestamp</th>

                <th className="py-3 pr-6">Brand</th>

                <th className="py-3 pr-6">Risk score</th>

                <th className="py-3 pr-6">URL</th>

                <th className="py-3">Actions taken</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-white/5 text-slate-200">
              {filteredHistory.map((row) => {
                return (
                  <tr key={row.id} className="align-top hover:bg-white/5">
                    <td className="py-3 pr-6 text-xs text-slate-300">
                      {row.detectedAt
                        ? new Date(row.detectedAt).toLocaleString()
                        : "Unknown"}
                    </td>

                    <td className="py-3 pr-6 font-medium">{row.brand}</td>

                    <td className="py-3 pr-6">
                      <span className="inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-semibold">
                        <span className="text-accent-400">
                          {row.riskScore != null
                            ? `${row.riskScore}%`
                            : "Pending"}
                        </span>

                        <span className="text-slate-400">
                          {row.riskLevel ?? "Unknown"}
                        </span>
                      </span>
                    </td>

                    <td className="py-3 pr-6">
                      {row.url ? (
                        <div className="space-y-3">
                          <button
                            type="button"
                            onClick={() => handleUrlPreviewClick(row)}
                            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                          >
                            <LinkIcon className="h-4 w-4" />
                            View URL
                          </button>
                          {isInlineUrlPreview && expandedUrlRowId === row.id && (
                            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-slate-300">
                              <p className="break-all text-slate-200">{row.url}</p>
                              <div className="mt-3 flex flex-wrap items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => handleInlineCopy(row)}
                                  className="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                                >
                                  Copy URL
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleInlineOpen(row)}
                                  className="inline-flex items-center gap-2 rounded-full border border-amber-400/40 px-3 py-1 font-semibold text-amber-200 transition hover:bg-amber-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400/60"
                                >
                                  Open in new tab
                                </button>
                              </div>
                              {inlineUrlFeedback.id === row.id && inlineUrlFeedback.state !== "idle" && (
                                <p className="mt-3 text-[11px] text-slate-400">
                                  {inlineUrlFeedback.state === "success"
                                    ? "Copied to clipboard"
                                    : "Copy failed. Try again."}
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">No URL supplied</span>
                      )}
                    </td>

                    <td className="py-3">
                      <div className="space-y-3">
                        <p className="text-xs text-slate-400">
                          {row.actionsTaken}
                        </p>

                        <div className="flex flex-wrap gap-2 text-xs">
                          <button
                            type="button"
                            onClick={() => setScreenshotDetection(row)}
                            disabled={!row.screenshotPath}
                            className={`inline-flex items-center gap-2 rounded-full px-4 py-2 font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
                              row.screenshotPath
                                ? "border border-white/20 text-slate-100 hover:bg-white/10"
                                : "border border-white/10 text-slate-500 cursor-not-allowed"
                            }`}
                          >
                            <PhotoIcon className="h-4 w-4" />
                            View screenshot
                          </button>

                          <button
                            type="button"
                            onClick={() => handleQuickAction("escalate", row)}
                            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                          >
                            <ArrowUpOnSquareIcon className="h-4 w-4" />
                            Escalate
                          </button>

                          <button
                            type="button"
                            onClick={() =>
                              handleQuickAction("false-positive", row)
                            }
                            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                          >
                            <FlagIcon className="h-4 w-4" />
                            Flag false positive
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}

              {!filteredHistory.length && (
                <tr>
                  <td
                    colSpan={5}
                    className="py-6 text-center text-sm text-slate-400"
                  >
                    {emptyStateMessage}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {escalationTarget && (
        <EscalationModal
          detection={escalationTarget}
          defaultEmails={lastEscalationEmails}
          submitting={escalationSubmitting}
          error={escalationError}
          onSubmit={handleEscalationSubmit}
          onCancel={handleEscalationCancel}
          onEmailsChange={handleEscalationEmailsChange}
        />
      )}

      {!isInlineUrlPreview && urlPreviewTarget?.url && (
        <UrlPreviewModal
          detection={urlPreviewTarget}
          onClose={closeUrlPreviewModal}
        />
      )}

      {screenshotDetection?.screenshotPath && (
        <ScreenshotModal
          detection={screenshotDetection}
          onClose={() => setScreenshotDetection(null)}
        />
      )}
    </div>
  );
}

export default HistoryPage;
