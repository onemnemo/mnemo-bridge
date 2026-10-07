"use strict";

/* Page logic. Conversion happens in Python; this drives the screens and
 * shows progress pushed back through appProgress and appDone. Scripts load in
 * order: util.js, app.js, pull.js, push.js, run.js, update.js. */

const state = {
  direction: "pull",     // "pull" (Notion → Mnemo) or "push"
  screen: "start",
  items: [],             // pages + databases from list_content
  selected: new Set(),   // ids chosen for pull
  loadedFor: "",         // the key those items were fetched with
  parentItems: [],
  parentsLoadedFor: "",
  parentId: null,
  parentTitle: "",
  packagePath: null,
  packageInfo: null,
  outputPath: "",
  running: false,
  startedAt: 0,
  unit: "page",          // what the working screen counts: "page" or "note"
  errorDetail: "",
  errorBack: "connect",
  retry: null,
  version: "",
  update: null,         // the release Python found, if any
  canOpenFolder: true,
};

/* pywebview injects window.pywebview.api asynchronously. */
function api() {
  return window.pywebview.api;
}

window.addEventListener("pywebviewready", async () => {
  const s = await api().get_state();
  state.version = s.version;
  state.canOpenFolder = s.canOpenFolder !== false;
  document.documentElement.dataset.platform = s.platform || "windows";
  if (s.platform === "mac") {
    $("win-max").title = "Zoom";
    $("win-max").setAttribute("aria-label", "Zoom");
  }
  $("version").textContent = "v" + s.version;
  if (s.token) $("token").value = s.token;
  $("remember-token").checked = s.rememberToken;
  setOutputPath(s.defaultOutput);
  // Says nothing unless a newer release exists.
  api().check_for_update();
});

$("win-min").addEventListener("click", () => api().window_minimize());
$("win-max").addEventListener("click", () => api().window_toggle_maximize());
$("win-close").addEventListener("click", () => api().window_close());

/* External links open in the real browser. */
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-url]");
  if (link) {
    event.preventDefault();
    api().open_url(link.dataset.url);
  }
});

const SCREENS = ["start", "connect", "pages", "ready", "source", "push-ready",
                 "working", "done", "error", "update"];

/* Which rail step each screen belongs to; screens not listed show no rail. */
const RAIL = { connect: 1, pages: 2, source: 2, ready: 3, "push-ready": 3 };

function show(name) {
  state.screen = name;
  for (const id of SCREENS) $("screen-" + id).hidden = id !== name;

  const step = RAIL[name];
  $("rail").hidden = !step;
  if (step) {
    $("step-2-name").textContent = state.direction === "pull" ? "Choose pages" : "Choose notes";
    for (const n of [1, 2, 3]) {
      const el = $("step-" + n);
      el.classList.toggle("now", n === step);
      el.classList.toggle("done", n < step);
      el.querySelector(".dot").textContent = n < step ? "✓" : String(n);
    }
  }
}

document.querySelectorAll("[data-go]").forEach((el) => {
  el.addEventListener("click", () => show(el.dataset.go));
});

function setDirection(which) {
  state.direction = which;
  $("dir-pull").classList.toggle("selected", which === "pull");
  $("dir-push").classList.toggle("selected", which === "push");
  $("dir-pull").setAttribute("aria-pressed", String(which === "pull"));
  $("dir-push").setAttribute("aria-pressed", String(which === "push"));
}
$("dir-pull").addEventListener("click", () => setDirection("pull"));
$("dir-push").addEventListener("click", () => setDirection("push"));

function token() {
  return $("token").value.trim();
}

$("token").addEventListener("change", persistToken);
$("remember-token").addEventListener("change", persistToken);
function persistToken() {
  api().remember_token(token(), $("remember-token").checked);
}

$("connect-continue").addEventListener("click", () => {
  if (!token()) {
    $("token").focus();
    return showError({ title: "Paste the integration secret first.", checks: [] }, "connect");
  }
  persistToken();
  // A different key sees a different workspace, so refetch when the key changes.
  if (state.direction === "pull") {
    show("pages");
    if (!state.items.length || state.loadedFor !== token()) loadPages();
  } else {
    show("source");
    if (!state.parentItems.length || state.parentsLoadedFor !== token()) loadParents();
  }
});
