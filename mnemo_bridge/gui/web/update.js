"use strict";

/* Called from Python only when a newer release exists. */
window.appUpdate = function (release) {
  state.update = release;
  $("update-text").textContent = `Version ${release.version} is available.`;
  $("update-notice").hidden = false;
  $("update-title").textContent = `What's new in ${release.version}`;
  $("update-sub").textContent = state.version
    ? `You're on ${state.version}.`
    : "";
  $("update-notes").textContent = release.notes || "";
  // Without release notes, link to the release page.
  $("update-link").dataset.url = release.url || "";
  $("update-link-wrap").hidden = Boolean(release.notes) || !release.url;
};

$("update-open").addEventListener("click", () => show("update"));
$("update-later").addEventListener("click", () => show("start"));

$("update-install").addEventListener("click", () => {
  $("update-install").disabled = true;
  $("update-later").disabled = true;
  $("update-progress").hidden = false;
  $("update-fill").style.width = "0%";
  $("update-stage").textContent = "Downloading…";
  api().download_update();
});

window.appUpdateProgress = function (percent) {
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  $("update-fill").style.width = pct + "%";
};

window.appUpdateReady = function () {
  $("update-fill").style.width = "100%";
  $("update-stage").textContent = "Restarting";
  api().install_update();  // the process ends inside this call
};

window.appUpdateFailed = function (message) {
  $("update-progress").hidden = true;
  $("update-install").disabled = false;
  $("update-later").disabled = false;
  state.retry = () => show("update");
  showError({
    title: "The update couldn't be installed.",
    checks: [
      message || "The download didn't finish.",
      "This version still works. You can try again later, or download the "
        + "latest release by hand.",
    ],
    detail: message || "",
  }, "start");
};
