import { useEffect, useState } from "react";
import { XMarkIcon } from "@heroicons/react/24/solid";
import {
  ArrowTopRightOnSquareIcon,
  DocumentDuplicateIcon,
  ExclamationTriangleIcon,
} from "@heroicons/react/24/outline";
import { copyTextToClipboard } from "../lib/clipboard.js";

function UrlPreviewModal({ detection, onClose }) {
  const url = detection?.url ?? "";
  const brand = detection?.brand ?? null;

  const [copyState, setCopyState] = useState("idle");

  useEffect(() => {
    setCopyState("idle");
  }, [url]);

  useEffect(() => {
    if (copyState === "idle") {
      return undefined;
    }

    const timer = setTimeout(() => {
      setCopyState("idle");
    }, 2500);

    return () => clearTimeout(timer);
  }, [copyState]);

  if (!url) {
    return null;
  }

  const handleCopyClick = async () => {
    const wasCopied = await copyTextToClipboard(url);
    setCopyState(wasCopied ? "success" : "error");
  };

  const handleOpenClick = () => {
    if (typeof window === "undefined") {
      return;
    }

    const confirmation = window.confirm(
      "Opening this URL will launch a new browser tab. Only proceed if you trust the destination.",
    );

    if (!confirmation) {
      return;
    }

    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) {
      onClose?.();
    }
  };

  const subtitle = brand ? `${brand} destination` : "Detected URL";
  const copyMessage = copyState === "success"
    ? "Copied to clipboard"
    : copyState === "error"
      ? "Copy failed. Try again." : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-10 backdrop-blur"
    >
      <div className="relative w-full max-w-md rounded-3xl border border-white/10 bg-slate-950/95 p-6 shadow-card">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close URL preview"
          className="absolute right-4 top-4 rounded-full bg-white/10 p-1 text-slate-200 hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
        >
          <XMarkIcon className="h-5 w-5" />
        </button>

        <p className="text-xs uppercase tracking-[0.4em] text-slate-400">Detected URL</p>
        <h3 className="mt-2 text-2xl font-semibold text-white">{subtitle}</h3>
        <p className="mt-3 text-sm text-slate-400">
          Review the destination carefully before interacting. Use the actions below to copy or open it in a new tab.
        </p>

        <div className="mt-5 space-y-3 rounded-2xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Full URL</p>
          <p className="break-all text-sm text-slate-200">{url}</p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            onClick={handleCopyClick}
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 font-semibold text-slate-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            <DocumentDuplicateIcon className="h-4 w-4" />
            Copy URL
          </button>
          <button
            type="button"
            onClick={handleOpenClick}
            className="inline-flex items-center gap-2 rounded-full border border-amber-400/40 px-4 py-2 font-semibold text-amber-200 transition hover:bg-amber-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400/60"
          >
            <ArrowTopRightOnSquareIcon className="h-4 w-4" />
            Open in new tab
          </button>
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-400/30 px-3 py-[6px] text-[11px] text-amber-200">
            <ExclamationTriangleIcon className="h-3.5 w-3.5" />
            External links may be malicious.
          </div>
        </div>

        {copyMessage && (
          <p className="mt-3 text-xs text-slate-400">{copyMessage}</p>
        )}
      </div>
    </div>
  );
}

export default UrlPreviewModal;
