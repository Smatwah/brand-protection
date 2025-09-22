const STORAGE_KEY = "brand-protection:last-escalation-emails";
const EMAIL_PATTERN = /^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i;

export function loadStoredEscalationEmails() {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch (error) {
    console.warn("Unable to load stored escalation emails", error);
    return "";
  }
}

export function saveStoredEscalationEmails(value) {
  if (typeof window === "undefined") return;
  try {
    const trimmed = value.trim();
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch (error) {
    console.warn("Unable to persist escalation emails", error);
  }
}

export function extractEmails(value) {
  if (!value) return [];
  return value
    .split(/[,;\n\r\t]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function findInvalidEmails(emails) {
  return emails.filter((email) => !EMAIL_PATTERN.test(email));
}

export function buildEscalationEvidence(detection) {
  if (!detection) return null;

  const evidence = {
    detection_id: detection.id ?? detection.detectionId ?? null,
    brand: detection.brand ?? null,
    risk_level: detection.riskLevel ?? detection.risk_level ?? null,
    risk_score: detection.riskScore ?? detection.risk_score ?? null,
    url: detection.url ?? null,
    detected_at: detection.detectedAt ?? detection.detected_at ?? null,
    actions_taken: detection.actionsTaken ?? detection.actions_taken ?? null,
    recommendation: detection.recommendation ?? null,
    description:
      detection.description ?? detection.report ?? detection.summary ?? null,
    explanation:
      detection.report ??
      detection.description ??
      detection.actionsTaken ??
      detection.recommendation ??
      null,
    screenshot:
      detection.screenshotPath ??
      detection.screenshot ??
      detection.screenshot_path ??
      null,
    logo: detection.logo ?? null,
  };

  return Object.fromEntries(
    Object.entries(evidence).filter(
      ([, value]) => value != null && value !== "",
    ),
  );
}

export { EMAIL_PATTERN as escalationEmailPattern };
