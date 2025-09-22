import { XMarkIcon } from "@heroicons/react/24/solid";
import { InformationCircleIcon } from "@heroicons/react/24/outline";

function ReportModal({ detection, onClose }) {
  if (!detection) return null;

  const riskScore =
    detection.riskScore != null && Number.isFinite(detection.riskScore)
      ? `${detection.riskScore}%`
      : "unknown";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-10 backdrop-blur">
      <div className="relative w-full max-w-xl rounded-3xl border border-white/10 bg-slate-950/95 p-6 shadow-card">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full bg-white/10 p-1 text-slate-200 hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
          aria-label="Close report"
        >
          <XMarkIcon className="h-5 w-5" />
        </button>

        <p className="text-xs uppercase tracking-[0.4em] text-slate-400">Detection report</p>
        <h3 className="mt-2 text-2xl font-semibold text-white">{detection.brand} alert</h3>

        <div className="mt-5 space-y-4 text-sm leading-6 text-slate-300">
          <p>
            This URL appears to impersonate {detection.brand}. Risk level is reported at {riskScore}. We recommend treating
            this detection as suspicious until the investigation is complete.
          </p>
          {detection.description && <p>{detection.description}</p>}
          {detection.report && <p>{detection.report}</p>}
          {detection.recommendation && (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
              <p className="font-medium text-white">Suggested action</p>
              <p className="mt-2 text-sm text-slate-300">{detection.recommendation}</p>
            </div>
          )}
        </div>

        {detection.url && (
          <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-slate-400">
            <p className="font-medium text-white">Full URL</p>
            <p className="mt-1 break-all text-slate-300">{detection.url}</p>
            <button
              type="button"
              onClick={() => navigator.clipboard?.writeText(detection.url)}
              className="mt-3 inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-medium text-slate-200 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
            >
              Copy URL
            </button>
          </div>
        )}

        <div className="mt-4 flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-slate-400">
          <InformationCircleIcon className="h-4 w-4 flex-none text-accent-400" />
          <span>
            Report generated from backend intelligence. For deeper context, open the screenshot evidence or the raw
            investigation report inside the analyst console.
          </span>
        </div>
      </div>
    </div>
  );
}

export default ReportModal;
