"use strict";

(function bootstrapTalk2DataUI() {
  const THEME_KEY = "talk2data.theme";
  const SIDEBAR_KEY = "talk2data.sidebarCollapsed";
  const desktopSidebar = window.matchMedia("(min-width: 961px)");
  const dockedInspector = window.matchMedia("(min-width: 1281px)");

  function byId(id) {
    return document.getElementById(id);
  }

  function setTheme(theme) {
    const resolved = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = resolved;
    try {
      window.localStorage.setItem(THEME_KEY, resolved);
    } catch (_) {
      // Theme persistence is a convenience only.
    }

    const button = byId("theme-toggle");
    if (button) {
      const next = resolved === "dark" ? "light" : "dark";
      button.setAttribute("aria-label", `Use ${next} theme`);
      button.setAttribute("title", `Use ${next} theme`);
      button.dataset.theme = resolved;
    }
  }

  function configuredTheme() {
    try {
      const stored = window.localStorage.getItem(THEME_KEY);
      if (stored === "light" || stored === "dark") return stored;
    } catch (_) {
      // Fall through to the intentionally dark chat default.
    }
    return "dark";
  }

  function setSidebarOpen(open) {
    if (desktopSidebar.matches) {
      document.body.classList.remove("sidebar-open");
      document.body.classList.toggle("sidebar-collapsed", !open);
      try {
        window.localStorage.setItem(SIDEBAR_KEY, String(!open));
      } catch (_) {
        // Sidebar persistence is a convenience only.
      }
    } else {
      document.body.classList.remove("sidebar-collapsed");
      document.body.classList.toggle("sidebar-open", open);
    }
    syncExpandedState();
  }

  function toggleSidebar() {
    const currentlyOpen = desktopSidebar.matches
      ? !document.body.classList.contains("sidebar-collapsed")
      : document.body.classList.contains("sidebar-open");
    setSidebarOpen(!currentlyOpen);
  }

  function setInspectorOpen(open) {
    if (dockedInspector.matches) {
      document.body.classList.remove("inspector-open");
      document.body.classList.toggle("inspector-closed", !open);
    } else {
      document.body.classList.remove("inspector-closed");
      document.body.classList.toggle("inspector-open", open);
    }
    syncExpandedState();
  }

  function toggleInspector() {
    const currentlyOpen = dockedInspector.matches
      ? !document.body.classList.contains("inspector-closed")
      : document.body.classList.contains("inspector-open");
    setInspectorOpen(!currentlyOpen);
  }

  function syncExpandedState() {
    const sidebarOpen = desktopSidebar.matches
      ? !document.body.classList.contains("sidebar-collapsed")
      : document.body.classList.contains("sidebar-open");
    const inspectorOpen = dockedInspector.matches
      ? !document.body.classList.contains("inspector-closed")
      : document.body.classList.contains("inspector-open");

    for (const id of ["sidebar-toggle", "mobile-menu"]) {
      const button = byId(id);
      if (button) button.setAttribute("aria-expanded", String(sidebarOpen));
    }
    for (const id of ["inspector-toggle", "inspector-close"]) {
      const button = byId(id);
      if (button) button.setAttribute("aria-expanded", String(inspectorOpen));
    }
  }

  function closeMobilePanels() {
    if (!desktopSidebar.matches) document.body.classList.remove("sidebar-open");
    if (!dockedInspector.matches) document.body.classList.remove("inspector-open");
    syncExpandedState();
  }

  function activateInspectorTab(name) {
    const tabs = document.querySelectorAll("[data-inspector-tab]");
    const panels = document.querySelectorAll("[data-inspector-panel]");
    let found = false;

    for (const tab of tabs) {
      const active = tab.dataset.inspectorTab === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      found ||= active;
    }
    for (const panel of panels) {
      const active = panel.dataset.inspectorPanel === name;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    }
    if (found) setInspectorOpen(true);
  }

  function showDialog(dialogOrId) {
    const dialog = typeof dialogOrId === "string" ? byId(dialogOrId) : dialogOrId;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    window.requestAnimationFrame(() => {
      const target = dialog.querySelector("input:not([disabled]), textarea:not([disabled]), button:not([disabled])");
      target?.focus({ preventScroll: true });
    });
  }

  function closeDialog(dialogOrId) {
    const dialog = typeof dialogOrId === "string" ? byId(dialogOrId) : dialogOrId;
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function showToast(message, timeout = 4200) {
    const region = byId("toast-region");
    if (!region || !message) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.textContent = String(message);
    region.appendChild(toast);
    window.setTimeout(() => toast.remove(), timeout);
  }

  async function copyText(value, successMessage = "Copied to clipboard.") {
    const text = String(value ?? "");
    try {
      await navigator.clipboard.writeText(text);
      showToast(successMessage);
      return true;
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      showToast(copied ? successMessage : "Copy failed. Select the value manually.");
      return copied;
    }
  }

  function autoGrow(textarea) {
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }

  function initializeShell() {
    setTheme(configuredTheme());

    if (desktopSidebar.matches) {
      let collapsed = false;
      try {
        collapsed = window.localStorage.getItem(SIDEBAR_KEY) === "true";
      } catch (_) {
        collapsed = false;
      }
      document.body.classList.toggle("sidebar-collapsed", collapsed);
      document.body.classList.remove("sidebar-open");
    } else {
      document.body.classList.remove("sidebar-collapsed", "sidebar-open");
    }

    if (dockedInspector.matches) {
      document.body.classList.remove("inspector-open");
      document.body.classList.toggle(
        "inspector-closed",
        document.body.dataset.inspectorDefault === "closed",
      );
    } else {
      document.body.classList.remove("inspector-closed", "inspector-open");
    }

    byId("theme-toggle")?.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    byId("sidebar-toggle")?.addEventListener("click", toggleSidebar);
    byId("mobile-menu")?.addEventListener("click", toggleSidebar);
    byId("inspector-toggle")?.addEventListener("click", toggleInspector);
    byId("inspector-close")?.addEventListener("click", () => setInspectorOpen(false));
    byId("mobile-backdrop")?.addEventListener("click", closeMobilePanels);

    for (const tab of document.querySelectorAll("[data-inspector-tab]")) {
      tab.addEventListener("click", () => activateInspectorTab(tab.dataset.inspectorTab));
      tab.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const tabs = [...document.querySelectorAll("[data-inspector-tab]")];
        const index = tabs.indexOf(tab);
        const offset = event.key === "ArrowRight" ? 1 : -1;
        const next = tabs[(index + offset + tabs.length) % tabs.length];
        next?.focus();
        if (next?.dataset.inspectorTab) activateInspectorTab(next.dataset.inspectorTab);
      });
    }

    for (const dialog of document.querySelectorAll("dialog")) {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMobilePanels();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        const question = byId("question");
        if (question && !question.disabled) {
          event.preventDefault();
          question.focus();
        }
      }
    });

    desktopSidebar.addEventListener("change", initializeResponsiveState);
    dockedInspector.addEventListener("change", initializeResponsiveState);
    syncExpandedState();
  }

  function initializeResponsiveState() {
    if (desktopSidebar.matches) {
      document.body.classList.remove("sidebar-open");
      let collapsed = false;
      try {
        collapsed = window.localStorage.getItem(SIDEBAR_KEY) === "true";
      } catch (_) {
        collapsed = false;
      }
      document.body.classList.toggle("sidebar-collapsed", collapsed);
    } else {
      document.body.classList.remove("sidebar-collapsed", "sidebar-open");
    }

    if (dockedInspector.matches) {
      document.body.classList.remove("inspector-open");
      document.body.classList.toggle(
        "inspector-closed",
        document.body.dataset.inspectorDefault === "closed",
      );
    } else {
      document.body.classList.remove("inspector-closed", "inspector-open");
    }
    syncExpandedState();
  }

  window.Talk2DataUI = Object.freeze({
    activateInspectorTab,
    autoGrow,
    closeDialog,
    closeMobilePanels,
    copyText,
    setInspectorOpen,
    setSidebarOpen,
    setTheme,
    showDialog,
    showToast,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeShell, { once: true });
  } else {
    initializeShell();
  }
})();
