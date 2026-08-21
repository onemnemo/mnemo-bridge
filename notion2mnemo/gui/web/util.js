"use strict";

const $ = (id) => document.getElementById(id);

function emoji(value) {
  const span = document.createElement("span");
  span.className = "emoji";
  span.textContent = value || "";
  return span;
}
function name(value) {
  const span = document.createElement("span");
  span.className = "name";
  span.textContent = value;
  return span;
}
function tag(value) {
  const span = document.createElement("span");
  span.className = "tag";
  span.textContent = value || "";
  return span;
}
function text(value) {
  return document.createTextNode(value);
}
function placeholder(list, message) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = message;
  list.replaceChildren(li);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value);
  return div.innerHTML;
}

/* The only markup in Python's prose is **bold**. */
function markup(value) {
  return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}
function cap(value) {
  return value ? value[0].toUpperCase() + value.slice(1) : "";
}
function clock(date) {
  return date.toTimeString().slice(0, 5);
}
function humanDuration(ms) {
  const seconds = Math.max(1, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}
