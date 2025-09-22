function stripTrailingSlash(value) {
  if (!value) return "";
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

const envBase = stripTrailingSlash(import.meta.env.VITE_API_BASE_URL?.toString().trim() ?? "");

const runtimeBaseHint = (() => {
  if (typeof window === "undefined") return "";
  const direct = window.__BRAND_PROTECTION_API_BASE__;
  if (typeof direct === "string") {
    return stripTrailingSlash(direct.trim());
  }
  if (direct && typeof direct === "object" && "toString" in direct) {
    return stripTrailingSlash(String(direct));
  }
  return "";
})();

const globalConfigBase = (() => {
  if (typeof window === "undefined") return "";
  const config = window.__BRAND_PROTECTION_CONFIG__ ?? window.__APP_CONFIG__ ?? {};
  const candidate =
    config.apiBase ??
    config.api_base ??
    config.backendUrl ??
    config.backend_url ??
    config.apiHost ??
    config.api_host ??
    config.baseUrl ??
    config.base_url;
  if (typeof candidate === "string") {
    return stripTrailingSlash(candidate.trim());
  }
  return "";
})();

const metaBase = (() => {
  if (typeof document === "undefined") return "";
  const element = document.querySelector('meta[name="brand-protection:api-base"]');
  if (!element) return "";
  const value = element.getAttribute("content");
  return stripTrailingSlash(value?.trim() ?? "");
})();

const fallbackBase = (() => {
  if (typeof window === "undefined") return "";
  const origin = window.location.origin;
  if (/:(5173|4173)$/.test(origin) || origin.includes("localhost:5173")) {
    return "http://127.0.0.1:8000";
  }
  return origin;
})();

function runtimeHttpBase() {
  return envBase || metaBase || runtimeBaseHint || globalConfigBase || fallbackBase;
}

function runtimeWsBase(base) {
  if (!base) return "";
  if (base.startsWith("https://")) {
    return `wss://${base.slice(8)}`;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice(7)}`;
  }
  return base;
}

const httpBase = runtimeHttpBase();
const wsBase = runtimeWsBase(httpBase);

function cleanPath(path) {
  if (!path) return "/";
  return path.startsWith("/") ? path : `/${path}`;
}

export function apiUrl(path) {
  const base = httpBase;
  if (!base) {
    return cleanPath(path);
  }
  return `${base}${cleanPath(path)}`;
}

export function resolveAssetUrl(path) {
  if (!path) return null;
  if (/^(?:https?|data|blob):/i.test(path)) return path;
  return apiUrl(path);
}

export function websocketUrl(path) {
  const cleaned = cleanPath(path);
  if (wsBase) {
    return `${wsBase}${cleaned}`;
  }
  if (cleaned.startsWith("ws")) {
    return cleaned;
  }
  const host = typeof window !== "undefined" ? window.location.host : "localhost:5173";
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${host}${cleaned}`;
}
