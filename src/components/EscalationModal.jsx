import { useEffect, useState } from "react";
import { XMarkIcon, PaperAirplaneIcon } from "@heroicons/react/24/solid";
import { ClockIcon, ShieldExclamationIcon, EnvelopeIcon } from "@heroicons/react/24/outline";

function EscalationModal({
  detection,
  defaultEmails = "",
  submitting = false,
  error = null,
  onSubmit,
  onCancel,
  onEmailsChange,
}) {
  const [emails, setEmails] = useState(defaultEmails ?? "");

  useEffect(() => {
    setEmails(defaultEmails ?? "");
  }, [defaultEmails]);

  if (!detection) return null;

  const detectedDisplay = detection.detectedAt
    ? new Date(detection.detectedAt).toLocaleString()
    : "Unknown";
  const riskScoreDisplay =
    detection.riskScore != null && Number.isFinite(detection.riskScore)
      ? `${detection.riskScore}%`
      : "Unknown";
  const explanationText =
    detection.report ??
    detection.description ??
    detection.actionsTaken ??
    detection.recommendation ??
    null;

  const handleSubmit = (event) => {
    event.preventDefault();
    if (submitting) return;
    onSubmit?.(emails.trim());
  };

  const handleChange = (event) => {
    const value = event.target.value;
    setEmails(value);
    if (onEmailsChange) onEmailsChange(value);
  };

  const handleCancel = () => {
    if (submitting) return;
    onCancel?.();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-10 backdrop-blur">
      <div className="relative w-full max-w-lg rounded-3xl border border-white/10 bg-slate-950/95 p-6 shadow-card">
        <button
          type="button"
          onClick={onCancel}
          className="absolute right-4 top-4 rounded-full bg-white/10 p-1 text-slate-200 hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
          aria-label="Close escalation dialog"
        >
          <XMarkIcon className="h-5 w-5" />
        </button>

        <div className="flex items-start gap-3">
          <div className="rounded-full bg-accent-500/10 p-2 text-accent-300">
            <ShieldExclamationIcon className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Escalation</p>
            <h2 className="mt-1 text-2xl font-semibold text-white">Send evidence package</h2>
            <p className="mt-2 text-sm text-slate-400">
              Provide one or more recipient emails (comma separated). We will include the screenshot, URL, risk score, AI
              explanation, and timestamp for detection {detection.id}.
            </p>
          </div>
        </div>

        <div className="mt-6 space-y-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-slate-300">
          <div className="flex items-center gap-2 text-sm text-white">
            <ShieldExclamationIcon className="h-4 w-4 text-danger-300" />
            <span>{detection.brand}</span>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-danger-500/10 px-3 py-1 font-semibold text-danger-200">
              Risk: {detection.riskLevel ?? "Unknown"}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-accent-500/10 px-3 py-1 font-semibold text-accent-200">
              Score: {riskScoreDisplay}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-1 text-slate-200">
              <ClockIcon className="h-4 w-4" />
              {detectedDisplay}
            </span>
          </div>
          {detection.url && (
            <p className="break-all text-xs text-slate-400">
              URL: <span className="text-slate-200">{detection.url}</span>
            </p>
          )}
          {explanationText && (
            <p className="text-xs text-slate-400">
              AI explanation: <span className="text-slate-200">{explanationText}</span>
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <label className="block text-xs uppercase tracking-[0.3em] text-slate-400">
            Recipient emails
            <div className="mt-2 flex items-start gap-2">
              <div className="flex-1">
                <input
                  type="text"
                  value={emails}
                  onChange={handleChange}
                  placeholder="security@example.com, takedown@example.com"
                  autoFocus
                  className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent-400 focus:outline-none focus:ring-1 focus:ring-accent-400"
                />
                <p className="mt-2 text-xs text-slate-500">
                  Separate multiple addresses with commas. We will remember the last list for your next escalation.
                </p>
              </div>
              <EnvelopeIcon className="mt-3 h-5 w-5 text-slate-500" />
            </div>
          </label>

          {error && (
            <div className="rounded-2xl border border-danger-400/40 bg-danger-400/10 px-4 py-3 text-xs text-danger-200">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCancel}
              disabled={submitting}
              className={`rounded-full border border-white/10 px-4 py-2 text-sm font-medium text-slate-200 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${submitting ? 'cursor-not-allowed opacity-60' : 'hover:bg-white/10'}`}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className={`inline-flex items-center gap-2 rounded-full border border-accent-400 px-4 py-2 text-sm font-semibold text-accent-100 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-400 ${
                submitting ? "cursor-not-allowed opacity-60" : "hover:bg-accent-400/10"
              }`}
            >
              <PaperAirplaneIcon className={`h-4 w-4 ${submitting ? "animate-pulse" : ""}`} />
              {submitting ? "Sending" : "Send escalation"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default EscalationModal;
