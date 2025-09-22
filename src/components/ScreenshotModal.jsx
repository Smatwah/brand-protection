import { useEffect, useMemo, useState } from "react";
import { ArrowPathIcon, ExclamationTriangleIcon } from "@heroicons/react/24/outline";
import { XMarkIcon } from "@heroicons/react/24/solid";

function ScreenshotModal({ detection, onClose }) {
  const screenshotUrl = detection?.screenshotPath ?? null;

  const [imageError, setImageError] = useState(false);
  const [cacheBuster, setCacheBuster] = useState(0);

  useEffect(() => {
    setImageError(false);
    setCacheBuster(0);
  }, [detection?.id, screenshotUrl]);

  const resolvedSrc = useMemo(() => {
    if (!screenshotUrl) return null;
    if (!cacheBuster) return screenshotUrl;
    const joiner = screenshotUrl.includes("?") ? "&" : "?";
    return `${screenshotUrl}${joiner}refresh=${cacheBuster}`;
  }, [screenshotUrl, cacheBuster]);

  if (!screenshotUrl) return null;

  const handleOpenInNewTab = () => {
    const link = document.createElement("a");
    link.href = screenshotUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.download = screenshotUrl.split("/").pop() ?? "screenshot.png";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleRetry = () => {
    setImageError(false);
    setCacheBuster((value) => value + 1);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-10 backdrop-blur">
      <div className="relative w-full max-w-4xl overflow-hidden rounded-3xl border border-white/10 bg-slate-950/95 shadow-card">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full bg-white/10 p-1.5 text-slate-200 hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
          aria-label="Close screenshot"
        >
          <XMarkIcon className="h-5 w-5" />
        </button>

        <div className="space-y-3 border-b border-white/5 p-6">
          <p className="text-xs uppercase tracking-[0.4em] text-slate-400">Detection screenshot</p>
          <div className="flex flex-col gap-1 text-sm text-slate-300">
            <span className="text-lg font-semibold text-white">{detection.brand}</span>
            {detection.description && <span>{detection.description}</span>}
            {detection.url && <span className="break-all text-xs text-slate-500">{detection.url}</span>}
          </div>
        </div>

        <div className="max-h-[70vh] overflow-auto bg-slate-900">
          {!imageError && resolvedSrc ? (
            <img
              key={resolvedSrc}
              src={resolvedSrc}
              alt={`Screenshot evidence for ${detection.brand}`}
              className="w-full object-contain"
              onError={() => setImageError(true)}
            />
          ) : (
            <div className="flex h-80 w-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-slate-300">
              <ExclamationTriangleIcon className="h-10 w-10 text-warning-400" />
              <p className="max-w-sm text-slate-200">
                We could not load the screenshot from the detection service. The file might have been removed or the
                backend is temporarily unreachable.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
                <button
                  type="button"
                  onClick={handleRetry}
                  className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                >
                  <ArrowPathIcon className="h-4 w-4" />
                  Retry now
                </button>
                <span className="text-slate-500">
                  Check that the API is running and the screenshot path is accessible.
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/5 p-4 text-sm text-slate-300">
          <span>Captured during backend inspection.</span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleOpenInNewTab}
              className="rounded-full border border-white/20 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
            >
              Open in new tab
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full bg-accent-500 px-4 py-2 text-xs font-semibold text-slate-950 transition hover:bg-accent-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ScreenshotModal;
