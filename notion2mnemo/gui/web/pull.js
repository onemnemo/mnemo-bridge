"use strict";

$("reload-pages").addEventListener("click", (e) => { e.preventDefault(); loadPages(); });

async function loadPages() {
  placeholder($("page-list"), "Loading pages");
  // Retry returns to this screen first, not just the call.
  state.retry = () => { show("pages"); loadPages(); };
  const result = await api().list_content(token());
  if (result.error) {
    placeholder($("page-list"), "Nothing loaded.");
    return showError(result.error, "connect");
  }
  state.items = result.items;
  state.loadedFor = token();
  // Sub-pages come along with their parent, so default to top-level items only.
  state.selected = new Set(result.items.filter((i) => !i.nested).map((i) => i.id));
  renderPages();
}

$("filter").addEventListener("input", renderPages);
$("select-all").addEventListener("change", () => {
  const top = state.items.filter((i) => !i.nested);
  if ($("select-all").checked) top.forEach((i) => state.selected.add(i.id));
  else state.selected.clear();
  renderPages();
});

function renderPages() {
  const needle = $("filter").value.trim().toLowerCase();
  const list = $("page-list");
  list.replaceChildren();

  const shown = state.items.filter((i) => !needle || i.title.toLowerCase().includes(needle));
  if (!shown.length) {
    placeholder(list, needle ? "No matches." : "No pages are connected to this integration.");
  }

  for (const item of shown) {
    const li = document.createElement("li");
    li.classList.toggle("on", state.selected.has(item.id));

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = state.selected.has(item.id);
    box.tabIndex = -1;

    li.append(box, emoji(item.emoji), name(item.title), tag(describe(item)));
    li.addEventListener("click", (event) => {
      const on = event.target === box ? box.checked : !box.checked;
      box.checked = on;
      if (on) state.selected.add(item.id);
      else state.selected.delete(item.id);
      li.classList.toggle("on", on);
      updateCount();
    });
    list.append(li);
  }
  updateCount();
}

function describe(item) {
  if (item.kind === "database") return item.nested ? "database, inside a page" : "database";
  return item.nested ? "inside another page" : "";
}

function updateCount() {
  const total = state.items.length;
  const n = state.selected.size;
  $("selection-count").textContent = total ? `${n} of ${total} selected` : "";
  const top = state.items.filter((i) => !i.nested);
  $("select-all").checked = top.length > 0 && top.every((i) => state.selected.has(i.id));
  $("pages-continue").disabled = n === 0;
}

$("pages-continue").addEventListener("click", () => {
  const n = state.selected.size;
  $("ready-summary").textContent =
    `${cap(plural(n, "page"))} and the pages inside them.`;
  show("ready");
});

function setOutputPath(path) {
  state.outputPath = path || "";
  const parts = state.outputPath.split(/[\\/]/);
  const file = parts.pop() || "notion-export.mnemo";
  const dir = parts.pop() || "";
  $("output-name").textContent = file;
  $("output-dir").textContent = dir ? "in " + dir : "";
}

$("pick-output").addEventListener("click", async () => {
  const path = await api().pick_output_path(state.outputPath);
  if (path) setOutputPath(path);
});

$("rename-folder").addEventListener("click", () => {
  $("opt-folder").focus();
  $("opt-folder").select();
});

$("run-pull").addEventListener("click", runPull);

async function runPull() {
  const chosen = state.items.filter((i) => state.selected.has(i.id));
  state.retry = () => { show("ready"); runPull(); };
  beginRun("Exporting", "page");
  const result = await api().start_pull({
    token: token(),
    output: state.outputPath,
    pageIds: chosen.filter((i) => i.kind === "page").map((i) => i.id),
    databaseIds: chosen.filter((i) => i.kind === "database").map((i) => i.id),
    folder: $("opt-folder").value.trim(),
    covers: $("opt-covers").checked,
    dbProperties: $("opt-dbprops").checked,
    limit: $("opt-limit").value || null,
  });
  if (result.error) appDone({ error: result.error });
}
