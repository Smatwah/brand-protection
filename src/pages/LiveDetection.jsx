import { useNavigate, useParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowPathIcon,
  ArrowUpOnSquareIcon,
  FlagIcon,
  InformationCircleIcon,
  PhotoIcon,
  ShieldExclamationIcon,
} from "@heroicons/react/24/outline";
import ReportModal from "../components/ReportModal.jsx";
import ScreenshotModal from "../components/ScreenshotModal.jsx";
import EscalationModal from "../components/EscalationModal.jsx";
import { apiUrl, resolveAssetUrl, websocketUrl } from "../lib/api.js";
import {
  buildEscalationEvidence,
  extractEmails,
  findInvalidEmails,
  loadStoredEscalationEmails,
  saveStoredEscalationEmails,
} from "../lib/escalation.js";

const POLL_INTERVAL_MS = 4000;
const MAX_LIVE_DETECTIONS = 50;
const HISTORY_PAGE_SIZE = 100;
const MAX_HISTORY_LIMIT = 500;
const HISTORY_DEBOUNCE_MS = 350;
const RISK_LEVEL_OPTIONS = ["High", "Medium", "Low", "Unknown"];

const DETECTION_VIEW_OPTIONS = [
  {
    id: "url",
    label: "URL + Summary",
    description: "Detected destination and narrative overview.",
  },
  {
    id: "risk",
    label: "Risk Score + Action",
    description: "AI-backed guidance with suggested response.",
  },
  {
    id: "all",
    label: "All",
    description: "Show the complete detection package.",
  },
];

const KEYWORD_STOPWORDS = new Set([
  "the",
  "and",
  "for",
  "with",
  "that",
  "from",
  "this",
  "have",
  "your",
  "their",
  "into",
  "about",
  "http",
  "https",
]);

const relativeTime = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const timeDivisions = [
  { amount: 60, name: "seconds" },
  { amount: 60, name: "minutes" },
  { amount: 24, name: "hours" },
  { amount: 7, name: "days" },
  { amount: 4.34524, name: "weeks" },
  { amount: 12, name: "months" },
  { amount: Number.POSITIVE_INFINITY, name: "years" },
];

function formatRelativeTime(date) {
  if (!date) return "";
  const now = new Date();
  const then = new Date(date);
  let duration = (then - now) / 1000;

  for (const division of timeDivisions) {
    if (Math.abs(duration) < division.amount) {
      return relativeTime.format(Math.round(duration), division.name);
    }
    duration /= division.amount;
  }
  return "just now";
}

function formatExactTime(date) {
  if (!date) return "";
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString();
}

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

function normalisePercentage(value) {
  if (value == null) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  const scaled = numeric <= 1 ? numeric * 100 : numeric;
  return Math.round(scaled * 10) / 10;
}

function truncateUrl(url, limit = 80) {
  if (!url || typeof url !== "string") return "";
  if (url.length <= limit) return url;
  return `${url.slice(0, limit - 3)}...`;
}

function normaliseTimestamp(value) {
  if (!value && value !== 0) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    const ms = value > 1e12 ? value : value * 1000;
    const date = new Date(ms);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const numeric = Number(trimmed);
    if (Number.isFinite(numeric)) {
      const ms = numeric > 1e12 ? numeric : numeric * 1000;
      const fromNumeric = new Date(ms);
      if (!Number.isNaN(fromNumeric.getTime())) {
        return fromNumeric.toISOString();
      }
    }
    const parsed = new Date(trimmed);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }
  try {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  } catch {
    return null;
  }
}

function detectionDateValue(input) {
  if (!input) return 0;
  const source =
    typeof input === "object" && "detectedAt" in input
      ? input.detectedAt
      : input;
  if (!source) return 0;
  const time = Date.parse(source);
  return Number.isNaN(time) ? 0 : time;
}

function buildCompositeKey(detectedAt, url, fallbackIndex) {
  const ts = detectedAt ?? "";
  const trimmedUrl = typeof url === "string" ? url.trim() : "";
  const safeUrl = trimmedUrl || `row-${fallbackIndex}`;
  const safeTs = ts || "unknown-ts";
  return `${safeTs}::${safeUrl}`;
}

function upsertUniqueDetection(idMap, compositeIndex, detection) {
  if (!detection || !detection.id) return;

  const nextTimestamp = detectionDateValue(detection);

  const byId = idMap.get(detection.id);
  if (byId) {
    const existingTimestamp = detectionDateValue(byId);
    if (nextTimestamp >= existingTimestamp) {
      idMap.set(detection.id, detection);
      if (detection.compositeKey) {
        compositeIndex.set(detection.compositeKey, detection.id);
      }
    }
    return;
  }

  if (detection.compositeKey && compositeIndex.has(detection.compositeKey)) {
    const existingId = compositeIndex.get(detection.compositeKey);
    const existingDetection = idMap.get(existingId);
    if (existingDetection) {
      const existingTimestamp = detectionDateValue(existingDetection);
      if (nextTimestamp >= existingTimestamp) {
        idMap.set(existingId, detection);
      }
      return;
    }
  }

  idMap.set(detection.id, detection);
  if (detection.compositeKey) {
    compositeIndex.set(detection.compositeKey, detection.id);
  }
}

function normaliseDetection(item, index) {
  if (!item) return null;

  const riskScore = normaliseRiskScore(item.risk_score ?? item.riskScore);
  const riskLevel = normaliseRiskLevel(item.risk_level ?? item.riskLevel);
  const screenshotPath = resolveAssetUrl(
    item.screenshot_path ?? item.screenshotPath ?? item.screenshot ?? null,
  );

  const detectionIdCandidates = [
    item.id,
    item.detection_id,
    item.detectionId,
    item.uuid,
    item.guid,
    item.report_id,
    item.reportId,
    item.item?.id,
  ];
  const detectionId =
    detectionIdCandidates
      .map((candidate) => {
        if (candidate == null) return null;
        const value = String(candidate).trim();
        return value ? value : null;
      })
      .find(Boolean) ?? null;

  const urlCandidates = [
    item.url,
    item.full_url,
    item.fullUrl,
    item.target_url,
    item.targetUrl,
    item.destination_url,
    item.destinationUrl,
    item.link,
    item.item?.url,
  ];
  const urlValue =
    urlCandidates.find(
      (candidate) => typeof candidate === "string" && candidate.trim(),
    ) ?? "";
  const cleanedUrl = urlValue.trim();

  const timestampCandidates = [
    item.detected_at,
    item.detectedAt,
    item.timestamp,
    item.created_at,
    item.createdAt,
    item.first_seen_at,
    item.firstSeenAt,
    item.item?.detected_at,
    item.item?.timestamp,
  ];
  let detectedAt = null;
  for (const candidate of timestampCandidates) {
    detectedAt = normaliseTimestamp(candidate);
    if (detectedAt) break;
  }
  if (!detectedAt) {
    detectedAt = new Date().toISOString();
  }

  const compositeKey = buildCompositeKey(detectedAt, cleanedUrl, index);
  const uniqueId = detectionId ?? compositeKey;

  const logoPayload = item.logo ?? {};
  const logoMatchesRaw = Array.isArray(logoPayload.matches)
    ? logoPayload.matches
    : [];
  const logoMatches = logoMatchesRaw.map((entry, matchIndex) => ({
    label: entry?.label ?? entry?.name ?? `Match ${matchIndex + 1}`,
    confidence: normalisePercentage(entry?.confidence ?? entry?.score ?? null),
    boundingBox: entry?.bounding_box ?? entry?.boundingBox ?? null,
  }));
  const logoSimilarity = normalisePercentage(
    logoPayload.similarity ??
      logoPayload.similarity_percent ??
      logoPayload.similarityPercent ??
      logoPayload.similarity_score ??
      logoPayload.similarityScore ??
      null,
  );
  const logoAnnotatedPath = resolveAssetUrl(
    logoPayload.annotated_path ?? logoPayload.annotatedPath ?? null,
  );
  const logoMatchPath = resolveAssetUrl(
    logoPayload.match_path ??
      logoPayload.matchPath ??
      logoPayload.matched_region_path ??
      logoPayload.matchedRegionPath ??
      null,
  );
  const logoBoundingBox =
    logoPayload.bounding_box ?? logoPayload.boundingBox ?? null;
  const logoDetected =
    Boolean(logoPayload.detected) ||
    logoMatches.length > 0 ||
    Boolean(logoAnnotatedPath || logoMatchPath);

  return {
    id: uniqueId,
    detectionId,
    compositeKey,
    brand: item.brand ?? item.brand_name ?? "Unknown brand",
    riskScore,
    riskLevel,
    detectedAt,
    description: item.description ?? item.summary ?? "",
    recommendation: item.recommendation ?? null,
    url: cleanedUrl,
    screenshotPath,
    report: item.report ?? item.analysis ?? null,
    logo: {
      matches: logoMatches,
      similarity: logoSimilarity,
      annotatedPath: logoAnnotatedPath,
      matchPath: logoMatchPath,
      detected: logoDetected,
      boundingBox: logoBoundingBox,
    },
  };
}

function normaliseDetections(payload, options = {}) {
  const { max = Infinity } = options;
  const list = Array.isArray(payload) ? payload : payload ? [payload] : [];
  const byId = new Map();
  const byComposite = new Map();

  list.forEach((item, index) => {
    const detection = normaliseDetection(item, index);
    if (!detection) return;
    upsertUniqueDetection(byId, byComposite, detection);
  });

  const ordered = Array.from(byId.values()).sort((a, b) => {
    const delta = detectionDateValue(b) - detectionDateValue(a);
    if (delta !== 0) return delta;
    return a.id.localeCompare(b.id);
  });

  return max === Infinity ? ordered : ordered.slice(0, max);
}

function mergeDetections(existing, incoming, max = MAX_LIVE_DETECTIONS) {
  if (!incoming.length && !existing.length) return [];
  if (!incoming.length) {
    return existing
      .slice()
      .sort((a, b) => detectionDateValue(b) - detectionDateValue(a))
      .slice(0, max);
  }

  const byId = new Map();
  const byComposite = new Map();

  existing.forEach((det) => {
    if (!det) return;
    upsertUniqueDetection(byId, byComposite, det);
  });

  incoming.forEach((det) => {
    if (!det) return;
    upsertUniqueDetection(byId, byComposite, det);
  });

  return Array.from(byId.values())
    .sort((a, b) => detectionDateValue(b) - detectionDateValue(a))
    .slice(0, max);
}

function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);

  return debounced;
}

function riskTone(score) {
  if (score == null) return "bg-slate-600/40";
  if (score >= 76) return "bg-danger-400";
  if (score >= 26) return "bg-warning-400";
  return "bg-success-400";
}

function riskBadgeClasses(level) {
  switch (level) {
    case "High":
      return "border-danger-400/30 bg-danger-400/10 text-danger-200";
    case "Medium":
      return "border-warning-400/30 bg-warning-400/10 text-warning-200";
    case "Low":
      return "border-success-400/30 bg-success-400/10 text-success-200";
    default:
      return "border-white/10 bg-white/5 text-slate-200";
  }
}

function LiveDetectionPage() {
  const detectionEndpoint = useMemo(() => apiUrl("/api/url-detection"), []);
  const historyEndpoint = useMemo(
    () => apiUrl("/api/url-detection/history"),
    [],
  );
  const escalationEndpoint = useMemo(
    () => apiUrl("/api/url-detection/escalate"),
    [],
  );
  const socketEndpoint = useMemo(() => websocketUrl("/ws/detections"), []);

  const navigate = useNavigate();
  const { view } = useParams();

  const activeDetectionView = useMemo(() => {
    const fallback = DETECTION_VIEW_OPTIONS[0].id;
    if (!view) return fallback;
    return DETECTION_VIEW_OPTIONS.some((option) => option.id === view)
      ? view
      : fallback;
  }, [view]);

  useEffect(() => {
    const fallback = DETECTION_VIEW_OPTIONS[0].id;
    if (!view || !DETECTION_VIEW_OPTIONS.some((option) => option.id === view)) {
      navigate(`/live/${fallback}`, { replace: true });
    }
  }, [view, navigate]);

  const [detections, setDetections] = useState([]);
  const [selectedDetection, setSelectedDetection] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [highlightedId, setHighlightedId] = useState(null);
  const [screenshotDetection, setScreenshotDetection] = useState(null);
  const [error, setError] = useState(null);
  const [actionFeedback, setActionFeedback] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [historyLimit, setHistoryLimit] = useState(HISTORY_PAGE_SIZE);
  const [historyFilters, setHistoryFilters] = useState({
    search: "",
    riskLevels: [...RISK_LEVEL_OPTIONS],
    dateFrom: "",
    dateTo: "",
  });
  const [escalationTarget, setEscalationTarget] = useState(null);
  const [escalationSubmitting, setEscalationSubmitting] = useState(false);
  const [escalationError, setEscalationError] = useState(null);
  const [lastEscalationEmails, setLastEscalationEmails] = useState(() =>
    loadStoredEscalationEmails(),
  );
  const [toastMessage, setToastMessage] = useState(null);

  const abortControllerRef = useRef(null);
  const socketRef = useRef(null);
  const reconnectRef = useRef(null);
  const latestIdRef = useRef(null);
  const lastSinceRef = useRef(null);
  const fetchQueueRef = useRef(null);
  const feedbackTimerRef = useRef(null);
  const expandedIdRef = useRef(expandedId);
  const historyAbortControllerRef = useRef(null);
  const historyRefreshRef = useRef(() => {});
  const latestHistoryFiltersRef = useRef(historyFilters);
  const historyLimitRef = useRef(historyLimit);
  const detectionsRef = useRef([]);

  const debouncedHistoryFilters = useDebouncedValue(
    historyFilters,
    HISTORY_DEBOUNCE_MS,
  );

  const windowSummary = useMemo(() => {
    const summary = {
      total: detections.length,
      riskCounts: { High: 0, Medium: 0, Low: 0, Unknown: 0 },
      brandsImpersonated: 0,
      topBrands: [],
      repeatedUrls: [],
      topKeywords: [],
      keyInsights: [],
    };

    if (!detections.length) {
      return summary;
    }

    const brandCounts = new Map();
    const urlCounts = new Map();
    const keywordCounts = new Map();

    detections.forEach((detection) => {
      const level = detection.riskLevel ?? "Unknown";
      summary.riskCounts[level] = (summary.riskCounts[level] ?? 0) + 1;

      const brand = detection.brand ?? "Unknown brand";
      brandCounts.set(brand, (brandCounts.get(brand) ?? 0) + 1);

      if (detection.url) {
        const baseUrl = detection.url.split(/[#?]/)[0];
        urlCounts.set(baseUrl, (urlCounts.get(baseUrl) ?? 0) + 1);
      }

      const textSource = [detection.description, detection.report]
        .filter(Boolean)
        .join(" ");
      if (textSource) {
        textSource
          .toLowerCase()
          .replace(/[^a-z0-9\s]/g, " ")
          .split(/\s+/)
          .filter(Boolean)
          .forEach((word) => {
            if (word.length < 3) return;
            if (KEYWORD_STOPWORDS.has(word)) return;
            keywordCounts.set(word, (keywordCounts.get(word) ?? 0) + 1);
          });
      }
    });

    summary.brandsImpersonated = brandCounts.size;
    summary.topBrands = Array.from(brandCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
    summary.repeatedUrls = Array.from(urlCounts.entries())
      .filter(([, count]) => count > 1)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
    summary.topKeywords = Array.from(keywordCounts.entries())
      .filter(([, count]) => count > 1)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    const insights = [];
    if (summary.topBrands.length) {
      const items = summary.topBrands.map(
        ([brand, count]) => `${brand} (${count})`,
      );
      insights.push(`Most targeted brands: ${items.join(", ")}.`);
    }
    if (summary.repeatedUrls.length) {
      const items = summary.repeatedUrls.map(
        ([url, count]) => `${truncateUrl(url, 40)} (${count})`,
      );
      insights.push(`Repeated URLs: ${items.join(", ")}.`);
    }
    if (summary.topKeywords.length) {
      const items = summary.topKeywords.map(([keyword]) => keyword);
      insights.push(`Common keywords: ${items.join(", ")}.`);
    }

    summary.keyInsights = insights;
    return summary;
  }, [detections]);

  const aggregatedSummaryText = useMemo(() => {
    if (!windowSummary.total) {
      return "Waiting for detections to populate the dashboard.";
    }
    const riskOrder = ["High", "Medium", "Low", "Unknown"];
    const riskStrings = riskOrder
      .filter((level) => windowSummary.riskCounts[level])
      .map(
        (level) =>
          `${windowSummary.riskCounts[level]} ${level.toLowerCase()} risk`,
      );
    const parts = [];
    if (riskStrings.length) {
      parts.push(`Risk mix: ${riskStrings.join(", ")}.`);
    }
    if (windowSummary.brandsImpersonated) {
      parts.push(
        `${windowSummary.brandsImpersonated} brand${windowSummary.brandsImpersonated === 1 ? "" : "s"} impersonated.`,
      );
    }
    if (windowSummary.topBrands.length) {
      parts.push(
        `Top brands: ${windowSummary.topBrands.map(([brand]) => brand).join(", ")}.`,
      );
    }
    if (windowSummary.repeatedUrls.length) {
      const items = windowSummary.repeatedUrls.map(
        ([url, count]) => `${truncateUrl(url, 40)} (${count})`,
      );
      parts.push(`Repeated URLs: ${items.join(", ")}.`);
    }
    return (
      parts.join(" ") ||
      "Detections are streaming with no notable patterns yet."
    );
  }, [windowSummary]);

  const insightList = windowSummary.keyInsights.length
    ? windowSummary.keyInsights
    : ["No repeating patterns detected yet."];

  useEffect(
    () => () => {
      if (feedbackTimerRef.current) {
        clearTimeout(feedbackTimerRef.current);
        feedbackTimerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    detectionsRef.current = detections;
  }, [detections]);

  useEffect(() => {
    expandedIdRef.current = expandedId;
  }, [expandedId]);

  useEffect(() => {
    if (activeDetectionView !== "url" && activeDetectionView !== "all") {
      setExpandedId(null);
    }
  }, [activeDetectionView]);

  useEffect(() => {
    latestHistoryFiltersRef.current = historyFilters;
  }, [historyFilters]);

  useEffect(() => {
    historyLimitRef.current = historyLimit;
  }, [historyLimit]);

  useEffect(() => {
    let isMounted = true;

    const fetchDetections = async (manual = false) => {
      try {
        abortControllerRef.current?.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;

        const limitParam = String(MAX_LIVE_DETECTIONS);
        let requestUrl = detectionEndpoint;
        if (typeof window !== "undefined") {
          try {
            const url = new URL(detectionEndpoint, window.location.origin);
            url.searchParams.set("limit", limitParam);
            if (lastSinceRef.current) {
              url.searchParams.set("since", lastSinceRef.current);
            }
            requestUrl = url.toString();
          } catch {
            const params = [`limit=${limitParam}`];
            if (lastSinceRef.current) {
              params.push(`since=${encodeURIComponent(lastSinceRef.current)}`);
            }
            const joiner = detectionEndpoint.includes("?") ? "&" : "?";
            requestUrl = `${detectionEndpoint}${joiner}${params.join("&")}`;
          }
        } else {
          const params = [`limit=${limitParam}`];
          if (lastSinceRef.current) {
            params.push(`since=${encodeURIComponent(lastSinceRef.current)}`);
          }
          const joiner = detectionEndpoint.includes("?") ? "&" : "?";
          requestUrl = `${detectionEndpoint}${joiner}${params.join("&")}`;
        }

        const response = await fetch(requestUrl, { signal: controller.signal });
        if (response.status === 404) {
          if (!isMounted) return;
          setError(null);
          return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const payload = await response.json();
        if (!isMounted) return;

        const normalised = normaliseDetections(payload, {
          max: MAX_LIVE_DETECTIONS,
        });
        if (!normalised.length) {
          setError(null);
          return;
        }

        let shouldRefreshHistory = false;
        let highlightId = null;
        const activeExpandedId = expandedIdRef.current;
        setDetections((prev) => {
          const prevIds = new Set(prev.map((item) => item.id));
          if (normalised.some((item) => !prevIds.has(item.id))) {
            shouldRefreshHistory = true;
            highlightId = normalised[0]?.id ?? highlightId;
          }
          const merged = mergeDetections(prev, normalised, MAX_LIVE_DETECTIONS);
          const nextPrimary = merged[0];
          if (nextPrimary) {
            if (!highlightId && nextPrimary.id !== latestIdRef.current) {
              highlightId = nextPrimary.id;
            }
            latestIdRef.current = nextPrimary.id;
            lastSinceRef.current =
              nextPrimary.detectedAt ?? lastSinceRef.current;
          }
          const expandedStillPresent =
            activeExpandedId &&
            merged.some((item) => item.id === activeExpandedId);
          if (activeExpandedId && !expandedStillPresent) {
            setExpandedId((prevExpandedId) =>
              prevExpandedId &&
              !merged.some((item) => item.id === prevExpandedId)
                ? null
                : prevExpandedId,
            );
          }
          return merged;
        });
        if (highlightId) {
          setHighlightedId(highlightId);
        }
        setError(null);
        if (shouldRefreshHistory && historyRefreshRef.current) {
          historyRefreshRef.current();
        }
      } catch (error) {
        if (!isMounted || error.name === "AbortError") return;
        console.error("Failed to fetch detections", error);
        setError({
          message: "Unable to reach the detection service right now.",
          hint: `Confirm the API endpoint ${detectionEndpoint} is reachable and responding.`,
          retrySeconds: Math.round(POLL_INTERVAL_MS / 1000),
          manual,
        });
      }
    };

    fetchQueueRef.current = fetchDetections;

    fetchDetections();
    const interval = setInterval(fetchDetections, POLL_INTERVAL_MS);

    return () => {
      isMounted = false;
      clearInterval(interval);
      abortControllerRef.current?.abort();
      fetchQueueRef.current = null;
    };
  }, [detectionEndpoint]);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      return () => undefined;
    }

    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      if (reconnectRef.current) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }

      try {
        const ws = new WebSocket(socketEndpoint);
        socketRef.current = ws;

        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data);
            if (parsed?.type === "detection" && parsed.data) {
              const normalised = normaliseDetections(parsed.data, {
                max: MAX_LIVE_DETECTIONS,
              });
              if (!normalised.length) return;
              let shouldRefreshHistory = false;
              let highlightId = null;
              const activeExpandedId = expandedIdRef.current;
              setDetections((prev) => {
                const prevIds = new Set(prev.map((item) => item.id));
                if (normalised.some((item) => !prevIds.has(item.id))) {
                  shouldRefreshHistory = true;
                  highlightId = normalised[0]?.id ?? highlightId;
                }
                const merged = mergeDetections(
                  prev,
                  normalised,
                  MAX_LIVE_DETECTIONS,
                );
                const nextPrimary = merged[0];
                if (nextPrimary) {
                  if (!highlightId && nextPrimary.id !== latestIdRef.current) {
                    highlightId = nextPrimary.id;
                  }
                  latestIdRef.current = nextPrimary.id;
                  lastSinceRef.current =
                    nextPrimary.detectedAt ?? lastSinceRef.current;
                }
                const expandedStillPresent =
                  activeExpandedId &&
                  merged.some((item) => item.id === activeExpandedId);
                if (activeExpandedId && !expandedStillPresent) {
                  setExpandedId((prevExpandedId) =>
                    prevExpandedId &&
                    !merged.some((item) => item.id === prevExpandedId)
                      ? null
                      : prevExpandedId,
                  );
                }
                return merged;
              });
              if (highlightId) {
                setHighlightedId(highlightId);
              }
              if (shouldRefreshHistory && historyRefreshRef.current) {
                historyRefreshRef.current();
              }
              setError(null);
            }
          } catch (err) {
            console.error("Failed to handle detection message", err);
          }
        };

        ws.onclose = () => {
          if (!cancelled) {
            reconnectRef.current = setTimeout(connect, 3000);
          }
        };

        ws.onerror = () => {
          try {
            ws.close();
          } catch (error) {
            console.error(error);
          }
        };
      } catch (error) {
        console.error("WebSocket connection error", error);
        reconnectRef.current = setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectRef.current) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      if (socketRef.current) {
        try {
          socketRef.current.close();
        } catch (error) {
          console.error(error);
        }
        socketRef.current = null;
      }
    };
  }, [socketEndpoint]);

  const fetchHistory = useCallback(
    async (filters, limit) => {
      historyAbortControllerRef.current?.abort();
      const controller = new AbortController();
      historyAbortControllerRef.current = controller;

      const effectiveLimit = Math.min(
        limit ?? HISTORY_PAGE_SIZE,
        MAX_HISTORY_LIMIT,
      );
      setHistoryLoading(true);
      setHistoryError(null);

      const activeFilters = filters ?? {};
      const searchValue =
        typeof activeFilters.search === "string"
          ? activeFilters.search.trim()
          : "";
      const rawRiskLevels = Array.isArray(activeFilters.riskLevels)
        ? activeFilters.riskLevels.filter(Boolean)
        : [];
      const riskLevels = RISK_LEVEL_OPTIONS.filter((level) =>
        rawRiskLevels.includes(level),
      );
      const dateFromIso = activeFilters.dateFrom
        ? (() => {
            const date = new Date(`${activeFilters.dateFrom}T00:00:00Z`);
            return Number.isNaN(date.getTime()) ? null : date.toISOString();
          })()
        : null;
      const dateToIso = activeFilters.dateTo
        ? (() => {
            const date = new Date(`${activeFilters.dateTo}T23:59:59Z`);
            return Number.isNaN(date.getTime()) ? null : date.toISOString();
          })()
        : null;

      const params = [`limit=${effectiveLimit}`];
      if (searchValue) {
        params.push(`search=${encodeURIComponent(searchValue)}`);
      }
      if (riskLevels.length && riskLevels.length < RISK_LEVEL_OPTIONS.length) {
        params.push(`risk_levels=${encodeURIComponent(riskLevels.join(","))}`);
      }
      if (dateFromIso) {
        params.push(`date_from=${encodeURIComponent(dateFromIso)}`);
      }
      if (dateToIso) {
        params.push(`date_to=${encodeURIComponent(dateToIso)}`);
      }

      try {
        let requestUrl = historyEndpoint;
        if (typeof window !== "undefined") {
          try {
            const url = new URL(historyEndpoint, window.location.origin);
            url.searchParams.set("limit", String(effectiveLimit));
            if (searchValue) {
              url.searchParams.set("search", searchValue);
            }
            if (
              riskLevels.length &&
              riskLevels.length < RISK_LEVEL_OPTIONS.length
            ) {
              url.searchParams.set("risk_levels", riskLevels.join(","));
            }
            if (dateFromIso) {
              url.searchParams.set("date_from", dateFromIso);
            }
            if (dateToIso) {
              url.searchParams.set("date_to", dateToIso);
            }
            requestUrl = url.toString();
          } catch {
            const joiner = historyEndpoint.includes("?") ? "&" : "?";
            requestUrl = `${historyEndpoint}${joiner}${params.join("&")}`;
          }
        } else {
          const joiner = historyEndpoint.includes("?") ? "&" : "?";
          requestUrl = `${historyEndpoint}${joiner}${params.join("&")}`;
        }

        const response = await fetch(requestUrl, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json();
        const rawItems = Array.isArray(payload?.items)
          ? payload.items
          : Array.isArray(payload)
            ? payload
            : [];
        const normalised = normaliseDetections(rawItems);
        const liveIds = new Set(detectionsRef.current.map((item) => item.id));
        const filtered = normalised.filter((item) => !liveIds.has(item.id));
        setHistory(filtered);
        setHistoryTotal(
          typeof payload?.total === "number"
            ? payload.total
            : normalised.length,
        );
      } catch (error) {
        if (error.name === "AbortError") {
          return;
        }
        console.error("Failed to fetch history", error);
        setHistoryError("Unable to load detection history right now.");
      } finally {
        setHistoryLoading(false);
      }
    },
    [historyEndpoint],
  );

  useEffect(() => {
    historyRefreshRef.current = () =>
      fetchHistory(latestHistoryFiltersRef.current, historyLimitRef.current);
  }, [fetchHistory]);

  useEffect(() => {
    fetchHistory(debouncedHistoryFilters, historyLimit);
  }, [debouncedHistoryFilters, historyLimit, fetchHistory]);

  useEffect(() => {
    if (!toastMessage) return;
    const timer = setTimeout(() => setToastMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [toastMessage]);

  useEffect(
    () => () => {
      historyAbortControllerRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!highlightedId) return;
    const timeout = setTimeout(() => setHighlightedId(null), 2200);
    return () => clearTimeout(timeout);
  }, [highlightedId]);

  const latestDetection = detections[0];
  const latestDetectedAt = latestDetection?.detectedAt ?? null;

  const handleManualRetry = useCallback(() => {
    setError(null);
    if (fetchQueueRef.current) {
      fetchQueueRef.current(true);
    }
  }, []);

  const handleQuickAction = useCallback(
    (action) => {
      if (action === "escalate") {
        if (!latestDetection) return;
        setEscalationTarget(latestDetection);
        setEscalationError(null);
        return;
      }

      if (feedbackTimerRef.current) {
        clearTimeout(feedbackTimerRef.current);
        feedbackTimerRef.current = null;
      }

      let message = "Action captured.";
      if (action === "false-positive") {
        message =
          "Marked as false positive. Analysts will review and suppress similar alerts.";
      }

      setActionFeedback(message);
      feedbackTimerRef.current = setTimeout(() => {
        setActionFeedback(null);
        feedbackTimerRef.current = null;
      }, 4000);
    },
    [latestDetection],
  );

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

  const handleHistorySearchChange = useCallback((event) => {
    const value = event.target.value;
    setHistoryFilters((prev) => ({ ...prev, search: value }));
    setHistoryLimit(HISTORY_PAGE_SIZE);
  }, []);

  const handleHistoryDateChange = useCallback(
    (field) => (event) => {
      const value = event.target.value;
      setHistoryFilters((prev) => ({ ...prev, [field]: value }));
      setHistoryLimit(HISTORY_PAGE_SIZE);
    },
    [],
  );

  const handleHistoryRiskToggle = useCallback((level) => {
    setHistoryFilters((prev) => {
      const exists = prev.riskLevels.includes(level);
      const nextLevels = exists
        ? prev.riskLevels.filter((item) => item !== level)
        : [...prev.riskLevels, level];
      const normalized = RISK_LEVEL_OPTIONS.filter((item) =>
        nextLevels.includes(item),
      );
      return { ...prev, riskLevels: normalized };
    });
    setHistoryLimit(HISTORY_PAGE_SIZE);
  }, []);

  const handleClearHistoryFilters = useCallback(() => {
    setHistoryFilters({
      search: "",
      riskLevels: [...RISK_LEVEL_OPTIONS],
      dateFrom: "",
      dateTo: "",
    });
    setHistoryLimit(HISTORY_PAGE_SIZE);
  }, []);

  const handleHistoryLoadMore = useCallback(() => {
    setHistoryLimit((prev) =>
      Math.min(prev + HISTORY_PAGE_SIZE, MAX_HISTORY_LIMIT),
    );
  }, []);

  const historyFiltersActive = useMemo(() => {
    return (
      historyFilters.search.trim() !== "" ||
      historyFilters.dateFrom !== "" ||
      historyFilters.dateTo !== "" ||
      historyFilters.riskLevels.length < RISK_LEVEL_OPTIONS.length
    );
  }, [historyFilters]);

  const hasMoreHistory =
    historyTotal > history.length && historyLimit < MAX_HISTORY_LIMIT;

  const deriveRiskInsights = (detection) => {
    const level = detection.riskLevel ?? "Unknown";

    let recommendedAction = detection.recommendation;
    if (!recommendedAction) {
      if (level === "High") {
        recommendedAction =
          "Immediate takedown request and escalate to the response team.";
      } else if (level === "Medium") {
        recommendedAction =
          "Monitor closely and prepare escalation if activity persists.";
      } else if (level === "Low") {
        recommendedAction =
          "Track in the watchlist and schedule periodic reviews.";
      } else {
        recommendedAction =
          "Monitor and gather additional evidence before acting.";
      }
    }

    let confidence = 70;
    if (level === "High") confidence = 95;
    else if (level === "Medium") confidence = 80;
    else if (level === "Low") confidence = 65;

    return {
      action: recommendedAction,
      confidence,
    };
  };

  const renderUrlSection = (detection, expanded) => {
    const hasUrl = Boolean(detection.url);

    const handleCopyClick = () => {
      if (!hasUrl) return;

      const value = detection.url;
      const fallbackCopy = () => {
        if (typeof document === "undefined") return false;
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        let copied = false;
        try {
          copied = document.execCommand("copy");
        } catch {
          copied = false;
        } finally {
          document.body.removeChild(textarea);
        }
        return copied;
      };

      const canUseNavigatorClipboard =
        typeof navigator !== "undefined" &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === "function";

      if (canUseNavigatorClipboard) {
        navigator.clipboard.writeText(value).catch(() => fallbackCopy());
      } else {
        fallbackCopy();
      }
    };

    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
            Detected URL
          </p>
          {!hasUrl ? (
            <p className="mt-2 text-sm text-slate-200">No URL captured.</p>
          ) : (
            <>
              <p className="mt-2 text-sm text-slate-200">
                Reveal or copy the destination when needed.
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <button
                  type="button"
                  onClick={handleCopyClick}
                  className="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                >
                  Copy URL
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setExpandedId((prev) =>
                      prev === detection.id ? null : detection.id,
                    )
                  }
                  className="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                >
                  {expanded ? "Hide Full URL" : "Show Full URL"}
                </button>
              </div>
              {expanded && (
                <p className="mt-3 break-all text-xs text-slate-400">
                  {detection.url}
                </p>
              )}
            </>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
            Summary
          </p>
          <p className="mt-2 text-sm text-slate-200">
            {detection.description ||
              "No summary available for this detection."}
          </p>
        </div>
      </div>
    );
  };

  const renderRiskSection = (detection) => {
    const riskScore = Number.isFinite(detection.riskScore)
      ? detection.riskScore
      : null;
    const barWidth =
      riskScore != null ? Math.min(Math.max(riskScore, 0), 100) : 0;
    const insights = deriveRiskInsights(detection);

    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-white">Risk assessment</p>
            <span
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase ${riskBadgeClasses(
                detection.riskLevel,
              )}`}
            >
              <span>{detection.riskLevel ?? "Unknown"}</span>
              {riskScore != null && (
                <span className="text-slate-200/70">{riskScore}%</span>
              )}
            </span>
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full ${riskTone(riskScore)}`}
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-slate-400">
            {detection.riskLevel
              ? `Category: ${detection.riskLevel}`
              : "Category pending"}
          </p>
        </div>

        <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/60 p-4">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
              Recommended action
            </p>
            <p className="mt-1 text-sm text-slate-200">{insights.action}</p>
          </div>
          {insights.confidence != null && (
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Confidence
              </p>
              <p className="mt-1 text-sm text-slate-200">
                {Math.round(insights.confidence)}%
              </p>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderAllSection = (detection, expanded) => (
    <div className="space-y-6">
      {renderUrlSection(detection, expanded)}
      {renderRiskSection(detection)}
    </div>
  );

  return (
    <div className="flex flex-col gap-8">
      {toastMessage && (
        <div className="fixed inset-x-0 top-6 z-40 flex justify-center px-4">
          <div className="max-w-xl rounded-full border border-success-400/40 bg-success-500/10 px-5 py-3 text-sm font-medium text-success-200 shadow-lg">
            {toastMessage}
          </div>
        </div>
      )}
      <section className="flex flex-col gap-8 lg:flex-row">
        <div className="glass flex-1 rounded-3xl p-6 shadow-card">
          <div className="flex flex-col gap-3 border-b border-white/5 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm uppercase tracking-[0.4em] text-slate-400">
                Live detection feed
              </p>
              <h2 className="text-2xl font-semibold text-white">
                Incoming Detection stream
              </h2>
            </div>
            <span className="rounded-full bg-success-400/10 px-4 py-1 text-xs font-medium uppercase text-success-400">
              Live stream with {Math.round(POLL_INTERVAL_MS / 1000)}s fallback
            </span>
          </div>

          {error && (
            <div className="mt-4 rounded-2xl border border-warning-400/40 bg-warning-400/10 p-4 text-sm text-warning-200">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <ShieldExclamationIcon className="h-5 w-5" />
                  <span className="font-semibold">{error.message}</span>
                </div>
                <button
                  type="button"
                  onClick={handleManualRetry}
                  className="inline-flex items-center gap-2 rounded-full border border-warning-400/40 px-3 py-1 text-xs font-semibold text-warning-100 transition hover:bg-warning-400/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-warning-400"
                >
                  <ArrowPathIcon className="h-4 w-4" />
                  Retry now
                </button>
              </div>
              <p className="mt-2 text-xs text-warning-200/80">{error.hint}</p>
              <p className="mt-1 text-xs text-warning-300/80">
                Automatic retry in approximately{" "}
                {error.retrySeconds ?? Math.round(POLL_INTERVAL_MS / 1000)}{" "}
                seconds.
              </p>
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-2">
            {DETECTION_VIEW_OPTIONS.map((option) => {
              const active = option.id === activeDetectionView;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => navigate(`/live/${option.id}`)}
                  className={`rounded-full px-4 py-2 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${
                    active
                      ? "bg-accent-500 text-slate-950 shadow-card"
                      : "border border-white/15 text-slate-300 hover:border-accent-400/60 hover:text-accent-200"
                  }`}
                  title={option.description}
                >
                  {option.label}
                </button>
              );
            })}
          </div>

          <ul className="mt-6 flex flex-col gap-4">
            {detections.map((detection) => {
              const relative = formatRelativeTime(detection.detectedAt);
              const exactTime = formatExactTime(detection.detectedAt);
              const allowExpansion =
                activeDetectionView === "url" || activeDetectionView === "all";
              const isExpanded = allowExpansion && expandedId === detection.id;
              const riskScore = Number.isFinite(detection.riskScore)
                ? detection.riskScore
                : null;
              const riskLabel =
                riskScore != null ? `${riskScore}%` : "Pending analysis";
              const viewContentMap = {
                url: renderUrlSection(detection, isExpanded),
                risk: renderRiskSection(detection),
                all: renderAllSection(detection, isExpanded),
              };
              const viewContent =
                viewContentMap[activeDetectionView] ??
                renderUrlSection(detection, isExpanded);

              return (
                <li
                  key={detection.id}
                  className={`glass rounded-2xl border border-white/5 p-4 transition duration-500 ${
                    highlightedId === detection.id
                      ? "ring-2 ring-accent-500/70 animate-pulseIn"
                      : ""
                  }`}
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <h3 className="text-lg font-semibold text-white">
                          {detection.brand}
                        </h3>
                        <span
                          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase ${riskBadgeClasses(
                            detection.riskLevel,
                          )}`}
                        >
                          <span>{detection.riskLevel ?? "Unknown"}</span>
                          {riskScore != null && (
                            <span className="text-slate-200/70">
                              {riskLabel}
                            </span>
                          )}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">
                        Detected {relative || "just now"}
                        {exactTime ? ` - ${exactTime}` : ""}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 space-y-6">{viewContent}</div>

                  <div className="mt-6 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedDetection(detection)}
                      className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                    >
                      <InformationCircleIcon className="h-4 w-4" />
                      View report
                    </button>
                    {detection.screenshotPath && (
                      <button
                        type="button"
                        onClick={() => setScreenshotDetection(detection)}
                        className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                      >
                        <PhotoIcon className="h-4 w-4" />
                        View screenshot
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
            {!detections.length && (
              <li className="rounded-2xl border border-dashed border-white/10 bg-slate-950/40 p-8 text-center text-sm text-slate-400">
                Waiting for detections from the backend service.
              </li>
            )}
          </ul>
        </div>

        <aside className="glass w-full max-w-xl self-start rounded-3xl p-6 shadow-card">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm uppercase tracking-[0.4em] text-slate-400">
                Window summary
              </p>
              <h2 className="text-2xl font-semibold text-white">
                Detection insights
              </h2>
            </div>
            <span className="rounded-full border border-white/15 px-3 py-1 text-xs font-semibold text-slate-200">
              {windowSummary.total} total
            </span>
          </div>

          <div className="mt-6 space-y-6 text-sm leading-6 text-slate-300">
            <div className="space-y-4 rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Overview
              </p>
              <p className="text-sm text-slate-200">{aggregatedSummaryText}</p>
              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-3">
                <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500">
                  Brands impersonated
                </p>
                <p className="mt-1 text-xl font-semibold text-white">
                  {windowSummary.brandsImpersonated}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {["High", "Medium", "Low", "Unknown"].map((level) => (
                  <div
                    key={level}
                    className="rounded-xl border border-white/10 bg-slate-950/60 p-3"
                  >
                    <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500">
                      {level} risk
                    </p>
                    <p className="mt-1 text-xl font-semibold text-white">
                      {windowSummary.riskCounts[level]}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Key insights
              </p>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {insightList.map((insight, index) => (
                  <li
                    key={`insight-${index}`}
                    className="flex items-start gap-2"
                  >
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-accent-400" />
                    <span>{insight}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Most recent detection
              </p>
              {latestDetection ? (
                <div className="mt-3 space-y-4">
                  <div>
                    <p className="text-lg font-semibold text-white">
                      {latestDetection.brand}
                    </p>
                    <p className="text-xs text-slate-400">
                      {latestDetectedAt
                        ? `${formatExactTime(latestDetectedAt)} (${formatRelativeTime(latestDetectedAt)})`
                        : "Timestamp unavailable"}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-semibold ${riskBadgeClasses(
                        latestDetection.riskLevel,
                      )}`}
                    >
                      {latestDetection.riskLevel ?? "Pending"}
                    </span>
                    <span className="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1 font-semibold text-slate-100">
                      {latestDetection.riskScore != null
                        ? `${latestDetection.riskScore}% risk`
                        : "Pending analysis"}
                    </span>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4 text-sm text-slate-200">
                    {latestDetection.description ||
                      "No additional context supplied by the detector."}
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => handleQuickAction("false-positive")}
                      className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                    >
                      <FlagIcon className="h-4 w-4" />
                      Flag as false positive
                    </button>
                    <button
                      type="button"
                      onClick={() => handleQuickAction("escalate")}
                      className="inline-flex items-center gap-2 rounded-full bg-accent-500 px-4 py-2 font-semibold text-slate-950 transition hover:bg-accent-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
                    >
                      <ArrowUpOnSquareIcon className="h-4 w-4" />
                      Escalate
                    </button>
                  </div>
                  {actionFeedback && (
                    <p className="text-xs text-success-300">{actionFeedback}</p>
                  )}
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-400">
                  We have not received any detections yet.
                </p>
              )}
            </div>
          </div>
        </aside>
      </section>

      <section className="glass rounded-3xl p-6 shadow-card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.4em] text-slate-400">
              Detection archive
            </p>
            <h2 className="text-2xl font-semibold text-white">History</h2>
            <p className="mt-1 text-xs text-slate-500">
              Showing {history.length} of {historyTotal} stored detections.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Search
              </label>
              <input
                type="text"
                value={historyFilters.search}
                onChange={handleHistorySearchChange}
                placeholder="Search brand or URL"
                className="w-56 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent-400 focus:outline-none focus:ring-1 focus:ring-accent-400"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">
                From
              </label>
              <input
                type="date"
                value={historyFilters.dateFrom}
                onChange={handleHistoryDateChange("dateFrom")}
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 focus:border-accent-400 focus:outline-none focus:ring-1 focus:ring-accent-400"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">
                To
              </label>
              <input
                type="date"
                value={historyFilters.dateTo}
                onChange={handleHistoryDateChange("dateTo")}
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 focus:border-accent-400 focus:outline-none focus:ring-1 focus:ring-accent-400"
              />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Risk
              </span>
              <div className="flex flex-wrap gap-2">
                {RISK_LEVEL_OPTIONS.map((level) => {
                  const active = historyFilters.riskLevels.includes(level);
                  return (
                    <button
                      key={level}
                      type="button"
                      onClick={() => handleHistoryRiskToggle(level)}
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
            {historyFiltersActive && (
              <button
                type="button"
                onClick={handleClearHistoryFilters}
                className="rounded-full border border-white/20 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {historyError && (
          <div className="mt-4 rounded-2xl border border-danger-400/40 bg-danger-400/10 p-4 text-sm text-danger-200">
            {historyError}
          </div>
        )}

        <div className="mt-6 overflow-x-auto">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="text-left text-xs uppercase tracking-[0.3em] text-slate-400">
              <tr>
                <th className="py-3 pr-6">Brand</th>
                <th className="py-3 pr-6">Detection date</th>
                <th className="py-3 pr-6">Risk</th>
                <th className="py-3 pr-6">Screenshot</th>
                <th className="py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-slate-200">
              {history.map((row) => (
                <tr key={row.id} className="hover:bg-white/5">
                  <td className="py-3 pr-6 font-medium">{row.brand}</td>
                  <td className="py-3 pr-6 text-slate-300">
                    {row.detectedAt ? formatExactTime(row.detectedAt) : "N/A"}
                  </td>
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
              {!history.length && (
                <tr>
                  <td
                    colSpan="5"
                    className="py-6 text-center text-sm text-slate-400"
                  >
                    {historyLoading
                      ? "Loading history?"
                      : "No archived detections match your filters yet."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
          <span>
            {historyLoading
              ? "Refreshing history�"
              : `Showing ${history.length} detection${history.length === 1 ? "" : "s"} of ${historyTotal}.`}
          </span>
          {hasMoreHistory && (
            <button
              type="button"
              onClick={handleHistoryLoadMore}
              disabled={historyLoading}
              className={`rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
                historyLoading
                  ? "cursor-not-allowed opacity-60"
                  : "hover:bg-white/10"
              }`}
            >
              Load more
            </button>
          )}
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

      {selectedDetection && (
        <ReportModal
          detection={selectedDetection}
          onClose={() => setSelectedDetection(null)}
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

export default LiveDetectionPage;
