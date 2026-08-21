"use strict";

function beginRun(title, unit) {
  state.running = true;
  state.startedAt = Date.now();
  state.unit = unit;
  $("working-title").textContent = title;
  $("working-sub").textContent = "Starting";
  $("working-now").textContent = "";
  $("progress-fill").style.width = "0%";
  document.querySelector(".track").classList.add("indeterminate");
  $("stop-run").disabled = false;
  $("stop-run").textContent = "Stop";
  $("started-at").textContent = "Started " + clock(new Date());
  show("working");
}

$("stop-run").addEventListener("click", () => {
  $("stop-run").disabled = true;
  $("stop-run").textContent = "Stopping…";
  $("working-sub").textContent = "Finishing the current page";
  api().cancel_run();
});

/* Called from Python: {text, index, total, label}. */
window.appProgress = function (payload) {
  if (typeof payload === "string") payload = { text: payload };
  const { index, total, label } = payload;

  if (index && total) {
    document.querySelector(".track").classList.remove("indeterminate");
    $("progress-fill").style.width = Math.round((index / total) * 100) + "%";
    const left = remaining(index, total);
    $("working-sub").textContent =
      `${cap(state.unit)} ${index} of ${total}` + (left ? ` · ${left}` : "");
    $("working-now").replaceChildren(emoji(emojiFor(label)), text(label || ""));
  } else if (payload.text) {
    $("working-now").replaceChildren(text(payload.text));
  }
};

/* No estimate until the rate has settled. */
function remaining(index, total) {
  const elapsed = Date.now() - state.startedAt;
  if (index < 2 || elapsed < 4000) return "";
  const per = elapsed / index;
  const left = Math.round((per * (total - index)) / 1000);
  if (left <= 5) return "nearly done";
  if (left < 60) return `about ${Math.max(10, Math.round(left / 10) * 10)} seconds left`;
  return `about ${Math.round(left / 60)} minute${Math.round(left / 60) === 1 ? "" : "s"} left`;
}

function emojiFor(label) {
  const hit = state.items.find((i) => i.title === label);
  return hit ? hit.emoji : "";
}

window.appDone = function (result) {
  state.running = false;

  if (result.error) return showError(result.error, state.direction === "pull" ? "ready" : "push-ready");

  const took = humanDuration(Date.now() - state.startedAt);
  const mark = $("screen-done").querySelector(".result-mark");

  if (result.cancelled) {
    mark.className = "result-mark stopped";
    mark.textContent = "■";
    $("done-title").textContent = "Stopped";
    const made = result.pagesCreated || 0;
    $("done-sub").textContent = state.direction === "push" && made > 0
      // Restarting would create those pages a second time.
      ? `${cap(plural(made, "page"))} ${made === 1 ? "was" : "were"} already created in Notion. `
        + `Delete ${made === 1 ? "it" : "them"} before you start again, or ${made === 1 ? "it is" : "they are"} created twice.`
      : "Nothing was saved.";
    $("done-next").hidden = true;
    $("open-folder").hidden = true;
    setWarnings([]);
    return show("done");
  }

  mark.className = "result-mark ok";
  mark.textContent = "✓";
  $("done-next").hidden = false;

  if (state.direction === "pull") {
    const parts = result.path.split(/[\\/]/);
    const file = parts.pop();
    const dir = parts.pop() || "";
    $("done-title").textContent = `Exported ${plural(result.notes, "note")}`;
    $("done-sub").textContent =
      `${file}${dir ? " in " + dir : ""}, ${result.sizeMb} MB, ${took}`;
    $("next-title").textContent = "Import it in Mnemo";
    setSteps([
      "In Mnemo, open <strong>Notes &gt; Import</strong>.",
      result.folder
        ? `Choose the file. The notes go in a folder called <strong>${escapeHtml(result.folder)}</strong>.`
        : "Choose the file. The notes go at the top level.",
    ]);
    $("open-folder").hidden = !state.canOpenFolder;
    $("open-folder").onclick = () => api().open_containing_folder(result.path);
  } else {
    $("done-title").textContent = `Created ${plural(result.pages, "page")} in Notion`;
    $("done-sub").textContent =
      `${plural(result.blocks, "block")}, ${plural(result.images, "image")}, ${took}`;
    $("next-title").textContent = "Find them in Notion";
    setSteps([
      `Open <strong>${escapeHtml(state.parentTitle)}</strong> in Notion.`,
      "The notes are new pages inside it.",
    ]);
    $("open-folder").hidden = true;
  }

  setWarnings(result.warnings || []);
  show("done");
};

function setSteps(lines) {
  const ol = $("next-steps");
  ol.replaceChildren();
  lines.forEach((line, i) => {
    const li = document.createElement("li");
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = String(i + 1);
    const body = document.createElement("span");
    body.innerHTML = line;  // callers escape every interpolated value
    li.append(num, body);
    ol.append(li);
  });
}

function setWarnings(warnings) {
  const has = warnings.length > 0;
  $("warn-notice").hidden = !has;
  $("warn-list").hidden = true;
  $("warn-toggle").textContent = "Show";
  if (!has) return;
  $("warn-text").textContent =
    `${cap(plural(warnings.length, "item"))} didn't convert exactly. Everything else did.`;
  $("warn-list").textContent = warnings.join("\n");
}

$("warn-toggle").addEventListener("click", () => {
  const list = $("warn-list");
  list.hidden = !list.hidden;
  $("warn-toggle").textContent = list.hidden ? "Show" : "Hide";
});

$("again").addEventListener("click", () => show("start"));
$("done-close").addEventListener("click", () => api().window_close());

/* `explanation` is Python's {title, checks[], detail}. */
function showError(explanation, back) {
  state.running = false;
  state.errorDetail = explanation.detail || explanation.title || "";
  state.errorBack = back;

  $("error-title").textContent = explanation.title || "Something went wrong.";
  const checks = explanation.checks || [];
  $("error-checks-wrap").hidden = checks.length === 0;
  $("checks-title").textContent = "What to check";

  const host = $("error-checks");
  host.replaceChildren();
  for (const check of checks) {
    const div = document.createElement("div");
    div.className = "check-line";
    div.innerHTML = markup(check);
    host.append(div);
  }
  show("error");
}

$("error-back").addEventListener("click", () => show(state.errorBack));
$("error-retry").addEventListener("click", () => {
  if (state.retry) state.retry();
  else show(state.errorBack);
});

$("copy-detail").addEventListener("click", async (event) => {
  event.preventDefault();
  const link = event.target;
  try {
    await navigator.clipboard.writeText(state.errorDetail);
    link.textContent = "Copied";
    setTimeout(() => (link.textContent = "copy the error details"), 1600);
  } catch {
    // Clipboard access can be refused: show the text instead.
    $("warn-list").hidden = false;
    $("warn-list").textContent = state.errorDetail;
  }
});
