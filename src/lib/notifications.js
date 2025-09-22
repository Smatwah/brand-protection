import { apiUrl, websocketUrl } from "./api.js";

const DEFAULT_LIMIT = 30;

function ensureJson(response) {
  if (!response?.ok) {
    throw new Error(Request failed with status );
  }
  return response.json();
}

export async function fetchNotifications({ limit = DEFAULT_LIMIT, signal } = {}) {
  const params = new URLSearchParams();
  if (limit) {
    params.set("limit", String(limit));
  }
  const base = apiUrl("/api/notifications");
  const url = params.size ? ${base}? : base;
  const response = await fetch(url, { signal });
  const data = await ensureJson(response);
  const notifications = Array.isArray(data?.notifications) ? data.notifications : [];
  return notifications;
}

export async function fetchNotificationSettings({ signal } = {}) {
  const response = await fetch(apiUrl("/api/settings/notifications"), { signal });
  const data = await ensureJson(response);
  if (!data || typeof data !== "object") {
    return { email: true, slack: true };
  }
  return {
    email: Boolean(data.email ?? true),
    slack: Boolean(data.slack ?? true),
  };
}

export async function updateNotificationSettings(preferences, { signal } = {}) {
  const payload = {
    email: Boolean(preferences?.email),
    slack: Boolean(preferences?.slack),
  };
  const response = await fetch(apiUrl("/api/settings/notifications"), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });
  const data = await ensureJson(response);
  return {
    email: Boolean(data?.email ?? payload.email),
    slack: Boolean(data?.slack ?? payload.slack),
  };
}

export function createNotificationSocket() {
  if (typeof window === "undefined" || typeof WebSocket === "undefined") {
    return null;
  }
  const endpoint = websocketUrl("/ws/notifications");
  try {
    return new WebSocket(endpoint);
  } catch (error) {
    console.error("Failed to open notification websocket", error);
    return null;
  }
}
