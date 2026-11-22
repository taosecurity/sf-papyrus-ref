// SPDX-License-Identifier: MIT
// Script for the site that "sf-papyrus-ref html" builds: search, theme switch and the left menu highlight.
// It builds every element with DOM calls (never innerHTML), so names from the sources cannot inject markup.
(function () {
  "use strict";
  var doc = document.documentElement;
  var root = doc.getAttribute("data-root") || "";

  // Theme: remembered per browser when storage works; the page still works when it doesn't.
  try {
    var saved = localStorage.getItem("sfpr-theme");
    if (saved === "light" || saved === "dark") doc.setAttribute("data-theme", saved);
  } catch (e) { /* storage blocked */ }

  function isDark() {
    var t = doc.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme");
    if (btn) btn.addEventListener("click", function () {
      var next = isDark() ? "light" : "dark";
      doc.setAttribute("data-theme", next);
      try { localStorage.setItem("sfpr-theme", next); } catch (e) { /* storage blocked */ }
    });

    // Left menu: highlight the section in view. Top is on while the page is scrolled to the top.
    var links = Array.prototype.slice.call(document.querySelectorAll(".menu a"));
    function onScroll() {
      var current = links[0];
      for (var i = 1; i < links.length; i++) {
        var id = links[i].getAttribute("href").slice(1);
        var el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top < 120) current = links[i];
      }
      links.forEach(function (a) { a.classList.toggle("on", a === current); });
    }
    if (links.length) {
      links[0].addEventListener("click", function (ev) { ev.preventDefault(); window.scrollTo(0, 0); });
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll();
    }

    setupSearch();
  });

  // Search: the index (assets/search-index.js) loads the first time the box is used.
  var KIND = { s: "script", f: "function", e: "event", t: "struct", p: "property" };
  var loading = false;
  var lastTry = 0;  // a failed load is tried again at most every 5 seconds, so typing doesn't pile up requests

  function showLoadError() {
    var box = document.getElementById("sugg");
    var q = document.getElementById("q");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (q && !q.value.trim()) { box.style.display = "none"; return; }  // nothing typed: nothing to show
    var msg = document.createElement("div");
    msg.className = "empty";
    msg.textContent = "The search index (assets/search-index.js) could not be loaded. Build the site again.";
    box.appendChild(msg);
    box.style.display = "block";
  }

  function loadIndex(then) {
    if (window.SFPR_INDEX) { then(); return; }
    if (loading) return;
    if (lastTry && Date.now() - lastTry < 5000) { showLoadError(); return; }
    loading = true;
    lastTry = Date.now();
    var s = document.createElement("script");
    s.src = root + "assets/search-index.js";
    function done() {
      loading = false;
      if (window.SFPR_INDEX) { lastTry = 0; then(); return; }
      // Missing file, blocked script or a broken index that never set SFPR_INDEX.
      if (s.parentNode) s.parentNode.removeChild(s);
      lastTry = Date.now();  // the 5 seconds count from the failure, however long the load took
      showLoadError();
    }
    s.onload = done;
    s.onerror = done;
    document.head.appendChild(s);
  }

  function setupSearch() {
    var q = document.getElementById("q");
    var box = document.getElementById("sugg");
    if (!q || !box) return;
    var sel = -1;

    function hide() { box.style.display = "none"; sel = -1; }

    function href(row) {
      var page = root + "s/" + row[3];
      if (row[2] === "s") return page;
      if (row[2] === "p") return page + "#L" + row[4];
      return page + "#m-" + row[0].toLowerCase();
    }

    function render() {
      var text = q.value.trim().toLowerCase();
      while (box.firstChild) box.removeChild(box.firstChild);
      sel = -1;
      if (!text || !window.SFPR_INDEX) { hide(); return; }
      var dot = text.indexOf(".");
      var scriptPart = dot > 0 ? text.slice(0, dot) : "";
      var namePart = dot > 0 ? text.slice(dot + 1) : text;
      var exact = [], starts = [], has = [];
      var rows = window.SFPR_INDEX;
      for (var i = 0; i < rows.length && exact.length + starts.length < 60; i++) {
        var r = rows[i];
        if (scriptPart && r[1].toLowerCase() !== scriptPart) continue;
        var n = r[0].toLowerCase();
        if (n === namePart) exact.push(r);
        else if (n.indexOf(namePart) === 0) starts.push(r);
        else if (has.length < 60 && n.indexOf(namePart) > 0) has.push(r);
      }
      exact.sort(function (a, b) { return (a[2] === "s" ? 0 : 1) - (b[2] === "s" ? 0 : 1); });
      var list = exact.concat(starts, has).slice(0, 40);
      if (!list.length) {
        var none = document.createElement("div");
        none.className = "empty";
        none.textContent = "Nothing matches. Try part of the name, or Script.Name.";
        box.appendChild(none);
      }
      list.forEach(function (r) {
        var a = document.createElement("a");
        a.href = href(r);
        a.setAttribute("role", "option");
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = KIND[r[2]] || r[2];
        var name = document.createElement("span");
        name.textContent = r[0];
        a.appendChild(tag);
        a.appendChild(name);
        if (r[1]) {
          var where = document.createElement("span");
          where.className = "where";
          where.textContent = "on " + r[1];
          a.appendChild(where);
        }
        box.appendChild(a);
      });
      box.style.display = "block";
    }

    // index.html?q=Name opens with that search filled in (handy for links and bookmarks).
    var start = new URLSearchParams(window.location.search).get("q");
    if (start) { q.value = start; loadIndex(render); }

    q.addEventListener("focus", function () { loadIndex(render); });
    q.addEventListener("input", function () { loadIndex(render); });
    q.addEventListener("keydown", function (ev) {
      var items = box.querySelectorAll("a");
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        if (!items.length) return;
        ev.preventDefault();
        if (sel >= 0) items[sel].classList.remove("sel");
        sel = ev.key === "ArrowDown" ? Math.min(sel + 1, items.length - 1) : Math.max(sel - 1, 0);
        items[sel].classList.add("sel");
        items[sel].scrollIntoView({ block: "nearest" });
      } else if (ev.key === "Enter") {
        var go = items[sel >= 0 ? sel : 0];
        if (go) window.location.href = go.href;
      } else if (ev.key === "Escape") {
        hide();
        q.blur();
      }
    });
    document.addEventListener("click", function (ev) {
      if (!box.contains(ev.target) && ev.target !== q) hide();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "/" && document.activeElement !== q) { ev.preventDefault(); q.focus(); }
    });
  }
})();
