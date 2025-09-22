export async function copyTextToClipboard(value) {
  if (!value) {
    return false;
  }

  const fallbackCopy = () => {
    if (typeof document === "undefined") {
      return false;
    }

    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "absolute";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();

    let successful = false;
    try {
      successful = document.execCommand("copy");
    } catch {
      successful = false;
    }

    document.body.removeChild(textarea);
    return successful;
  };

  const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : null;
  if (clipboard && typeof clipboard.writeText === "function") {
    try {
      await clipboard.writeText(value);
      return true;
    } catch {
      return fallbackCopy();
    }
  }

  return fallbackCopy();
}
