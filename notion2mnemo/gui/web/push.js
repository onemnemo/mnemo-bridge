"use strict";

$("pick-package").addEventListener("click", async () => {
  const info = await api().pick_package();
  if (!info) return;
  if (info.error) return showError(info.error, "source");
  state.packagePath = info.path;
  state.packageInfo = info;
  const file = info.path.split(/[\\/]/).pop();
  $("package-value").textContent =
    `${file}, ${plural(info.notes.length, "note")}, ${plural(info.images, "image")}`;
  updateSourceReady();
});

$("reload-parents").addEventListener("click", (e) => { e.preventDefault(); loadParents(); });

async function loadParents() {
  placeholder($("parent-list"), "Loading pages");
  state.retry = () => { show("source"); loadParents(); };
  const result = await api().list_content(token());
  if (result.error) {
    placeholder($("parent-list"), "Nothing loaded.");
    return showError(result.error, "connect");
  }
  state.parentItems = result.items.filter((i) => i.kind === "page");
  state.parentsLoadedFor = token();
  // A parent picked under the old key may not exist under this one.
  state.parentId = null;
  state.parentTitle = "";
  updateSourceReady();
  renderParents();
}

$("parent-filter").addEventListener("input", renderParents);

function renderParents() {
  const needle = $("parent-filter").value.trim().toLowerCase();
  const list = $("parent-list");
  list.replaceChildren();

  const shown = state.parentItems.filter((i) => !needle || i.title.toLowerCase().includes(needle));
  if (!shown.length) placeholder(list, needle ? "No matches." : "No pages are connected to this integration.");

  for (const item of shown) {
    const li = document.createElement("li");
    li.classList.toggle("on", state.parentId === item.id);
    li.append(emoji(item.emoji), name(item.title), tag(item.nested ? "inside another page" : ""));
    li.addEventListener("click", () => {
      state.parentId = item.id;
      state.parentTitle = item.title;
      renderParents();
      updateSourceReady();
    });
    list.append(li);
  }
}

function updateSourceReady() {
  $("source-continue").disabled = !state.packagePath || !state.parentId;
}

$("source-continue").addEventListener("click", () => {
  const info = state.packageInfo;
  $("push-summary").textContent =
    `${cap(plural(info.notes.length, "note"))} become new Notion pages.`;
  $("push-package-value").textContent = state.packagePath.split(/[\\/]/).pop();
  $("push-parent-value").textContent = state.parentTitle;
  show("push-ready");
});

$("run-push").addEventListener("click", runPush);

async function runPush() {
  state.retry = () => { show("push-ready"); runPush(); };
  beginRun("Creating pages", "note");
  const result = await api().start_push({
    token: token(),
    package: state.packagePath,
    parent: state.parentId,
    uploadImages: $("opt-upload-images").checked,
  });
  if (result.error) appDone({ error: result.error });
}
