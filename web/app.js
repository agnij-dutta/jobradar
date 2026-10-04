/* Job Radar client: filters the full snapshot in the browser. No framework. */
(function () {
  "use strict";
  var DATA = window.JOBRADAR;
  var $ = function (id) { return document.getElementById(id); };
  if (!DATA) {
    $("meta").textContent = "No data/jobs.js found. Run `jobradar sweep && jobradar build`.";
    return;
  }
  var META = DATA.meta, ALL = DATA.postings;
  var LEVELS = META.levels;
  var MEMBERS = META.region_members;
  var VOCAB = {}; META.vocab.forEach(function (v) { VOCAB[v] = 1; });
  var ALIASES = META.aliases || {};
  var COUNTRY_NAMES = {
    US: "United States", CA: "Canada", UK: "United Kingdom", IN: "India", DE: "Germany", FR: "France",
    NL: "Netherlands", ES: "Spain", PT: "Portugal", IE: "Ireland", PL: "Poland", CZ: "Czechia", SG: "Singapore",
    AE: "UAE", AU: "Australia", NZ: "New Zealand", JP: "Japan", KR: "South Korea", BR: "Brazil", MX: "Mexico",
    AR: "Argentina", CO: "Colombia", CH: "Switzerland", SE: "Sweden", IT: "Italy", IL: "Israel", HK: "Hong Kong",
    NG: "Nigeria", KE: "Kenya", ZA: "South Africa", PH: "Philippines", ID: "Indonesia", VN: "Vietnam",
    PK: "Pakistan", RO: "Romania", UA: "Ukraine", TR: "Turkey", EE: "Estonia", LT: "Lithuania", GR: "Greece"
  };
  var PAGE = 60;

  var st = {
    stack: [], region: "", unverified: false, mode: "", years: 11, strictYears: false,
    levels: [], comp: 0, requireComp: false, visa: false, eng: true, q: "", newOnly: false,
    sort: "score", shown: PAGE
  };

  // ---------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function regionHas(r, c) { return r === "GLOBAL" || r === c || (MEMBERS[r] || []).indexOf(c) >= 0; }
  function eligible(p, c) {
    if (p.x && p.x.indexOf(c) >= 0) return "no";
    if (p.s === "u" || !p.r.length) return "unknown";
    for (var i = 0; i < p.r.length; i++) if (regionHas(p.r[i], c)) return "yes";
    return "no";
  }
  function resolveTerm(t) { t = t.trim().toLowerCase(); return ALIASES[t] || t; }
  function stackScore(p, terms) {
    if (!terms.length) return { s: 0, hit: [], miss: [] };
    var tot = 0, hit = [], miss = [];
    var hay = (p.t + " " + (p.tm || "")).toLowerCase();
    terms.forEach(function (t) {
      var n = 0;
      if (VOCAB[t]) n = p.k[t] || 0; else if (hay.indexOf(t) >= 0) n = 3;
      if (!n) { miss.push(t); return; }
      tot += Math.min(1, 0.6 + Math.min(n, 5) * 0.06);
      hit.push(t + (n > 1 ? " x" + n : ""));
    });
    return { s: Math.round(1000 * tot / terms.length) / 10, hit: hit, miss: miss };
  }
  function fmtK(n) { return n >= 1000 ? Math.round(n / 1000) + "k" : String(n); }
  var MODE = { r: "Remote", h: "Hybrid", o: "Onsite", u: "Mode ?" };

  // ---------- evaluation (mirrors jobradar/search.py)
  function evaluate(p) {
    var why = [], cav = [], rej = [];
    if (st.eng && !p.e) rej.push("not an engineering role");
    if (st.q) {
      var hay = (p.c + " " + p.t + " " + (p.tm || "")).toLowerCase();
      if (hay.indexOf(st.q.toLowerCase()) < 0) rej.push("title/company filter");
    }
    var sc = stackScore(p, st.stack);
    if (st.stack.length) {
      if (sc.hit.length) { why.push("stack: " + sc.hit.join(", ")); if (sc.miss.length) cav.push("no mention of " + sc.miss.join(", ")); }
      else rej.push("stack: no requested term in the description");
    }
    if (st.region) {
      var e = eligible(p, st.region), where = p.r.join(", ") || "unspecified";
      if (e === "yes") why.push("open to " + st.region + " (" + where + ")" + (p.ge ? "" : ""));
      else if (e === "unknown") {
        if (st.unverified) cav.push("never says where it hires; " + st.region + " unverified");
        else rej.push("geo: says " + MODE[p.m] + " but never says where");
      } else rej.push(p.m === "r" ? "geo: 'Remote' but restricted to other countries" : "geo: onsite/hybrid in another country");
    }
    if (st.mode && p.m !== st.mode) rej.push("work mode filter");
    if (st.years < 11) {
      if (p.y == null) { if (st.strictYears) rej.push("years: not stated"); else cav.push("years not stated" + (p.py != null ? "; prefers " + p.py + "+" : "")); }
      else if (p.y > st.years) rej.push(p.pt ? "years: above max, title gives no hint" : "years: above max");
      else why.push("asks " + p.y + "+ years");
    } else if (st.strictYears && p.y == null) rej.push("years: not stated");
    if (st.levels.length) {
      if (p.lv == null) cav.push("level unknown");
      else if (st.levels.indexOf(p.lv) < 0) rej.push("level filter");
    }
    if (st.comp > 0) {
      if (!p.cp) { if (st.requireComp) rej.push("comp: none published"); else cav.push("no pay band published"); }
      else if (p.cp[1] < st.comp * 1000) rej.push("comp: below your minimum");
    } else if (st.requireComp && !p.cp) rej.push("comp: none published");
    if (st.visa && p.v === "n") rej.push("visa: no sponsorship");
    if (st.newOnly && META.previous_run_started_at && p.f <= META.previous_run_started_at) rej.push("not new since last sweep");
    if (st.newOnly && !META.previous_run_started_at) rej.push("not new since last sweep");
    if (p.st) cav.push("board failed to fetch on the last sweep; may be closed");
    return { ok: !rej.length, s: sc.s, why: why, cav: cav, rej: rej };
  }

  // ---------- render
  function badge(cls, text, title) {
    return '<span class="b ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + esc(text) + "</span>";
  }
  function card(p, r) {
    var b = [];
    var geoTxt = p.s === "g" ? "Worldwide" : p.s === "u" ? "Where? not stated" : p.r.join(" · ");
    var geoCls = p.s === "u" ? "warn" : (st.region ? (eligible(p, st.region) === "yes" ? "ok" : "bad") : "");
    b.push(badge(p.m === "r" ? "acc" : "", MODE[p.m]));
    b.push(badge(geoCls, (p.m === "r" && p.s === "r" ? "Remote only in " : "") + geoTxt, p.ge || ("from location: " + (p.l || ""))));
    if (p.y != null) b.push(badge(p.y >= 5 ? "warn" : "ok", p.y + "+ yrs", p.ye));
    else b.push(badge("", "yrs ?", p.py != null ? "prefers " + p.py + "+ years" : "no years stated"));
    if (p.lv != null) b.push(badge("mono", LEVELS[p.lv], "level from " + p.ls + (p.tl && LEVELS[p.lv] !== p.tl ? "; title says " + p.tl : "")));
    if (p.pt && p.y >= 5) b.push(badge("warn", "plain title, " + p.y + "+ yrs", p.ye));
    if (p.cp) b.push(badge("mono", "$" + fmtK(p.cp[0]) + "-" + fmtK(p.cp[1]) + (p.cp[2] !== "USD" ? " (" + p.cp[2] + ")" : ""), "pay band, " + (p.cp[3] === "ats" ? "from the ATS" : "parsed from text") + "; USD approx"));
    if (p.v === "n") b.push(badge("bad", "no visa", p.ve));
    else if (p.v === "y") b.push(badge("ok", "visa ok", p.ve));
    if (p.st) b.push(badge("warn", "stale"));
    var lis = r.why.map(function (w) { return "<li>" + esc(w) + "</li>"; })
      .concat(r.cav.map(function (c) { return '<li class="cav">' + esc(c) + "</li>"; })).join("");
    return '<li class="card"><div class="card-top"><span class="company">' + esc(p.c) +
      (p.d ? " · posted " + esc(p.d) : "") + "</span>" + (st.stack.length ? '<span class="score">' + r.s + "</span>" : "") +
      '</div><a class="title" href="' + esc(p.u) + '" target="_blank" rel="noopener">' + esc(p.t) + "</a>" +
      '<div class="badges">' + b.join("") + "</div>" + (lis ? '<ul class="why">' + lis + "</ul>" : "") +
      '<div class="loc">' + esc(p.l || "") + (p.tm ? " · " + esc(p.tm) : "") + "</div></li>";
  }

  var lastHits = [];
  function apply() {
    var hits = [], excl = {}, nEx = 0;
    for (var i = 0; i < ALL.length; i++) {
      var p = ALL[i], r = evaluate(p);
      if (r.ok) hits.push([p, r]);
      else { nEx++; var seen = {}; r.rej.forEach(function (x) { if (!seen[x]) { seen[x] = 1; excl[x] = (excl[x] || 0) + 1; } }); }
    }
    var cmp = {
      score: function (a, b) { return b[1].s - a[1].s || a[1].cav.length - b[1].cav.length || (b[0].d > a[0].d ? 1 : -1); },
      "new": function (a, b) { return (b[0].d || "") > (a[0].d || "") ? 1 : (b[0].d || "") < (a[0].d || "") ? -1 : 0; },
      comp: function (a, b) { return ((b[0].cp || [0, 0])[1]) - ((a[0].cp || [0, 0])[1]); },
      years: function (a, b) { var ya = a[0].y == null ? 99 : a[0].y, yb = b[0].y == null ? 99 : b[0].y; return ya - yb; }
    }[st.sort];
    hits.sort(cmp);
    lastHits = hits;
    $("count").textContent = hits.length.toLocaleString() + " of " + ALL.length.toLocaleString() + " postings match";
    var ex = Object.keys(excl).sort(function (a, b) { return excl[b] - excl[a]; });
    $("excludedSummary").textContent = nEx.toLocaleString() + " excluded. Why?";
    $("excluded").innerHTML = ex.map(function (k) { return "<li><b>" + excl[k].toLocaleString() + "</b><span>" + esc(k) + "</span></li>"; }).join("");
    render();
    saveHash();
  }
  function render() {
    var slice = lastHits.slice(0, st.shown);
    $("list").innerHTML = slice.length ? slice.map(function (h) { return card(h[0], h[1]); }).join("")
      : '<li class="empty">Nothing matches. Open "Why?" above to see which filter removed what.</li>';
    $("more").hidden = lastHits.length <= st.shown;
  }

  // ---------- state <-> controls
  function readControls() {
    st.stack = $("stack").value.split(",").map(resolveTerm).filter(Boolean);
    st.region = $("region").value;
    st.unverified = $("unverified").checked;
    st.years = +$("years").value;
    st.strictYears = $("strictYears").checked;
    st.comp = +$("comp").value;
    st.requireComp = $("requireComp").checked;
    st.visa = $("visa").checked;
    st.eng = $("eng").checked;
    st.q = $("q").value.trim();
    st.newOnly = $("newOnly").checked;
    st.sort = $("sort").value;
    st.shown = PAGE;
    $("yearsOut").textContent = st.years >= 11 ? "any" : st.years + " yrs";
    $("compOut").textContent = st.comp ? "$" + st.comp + "k+" : "any";
    try { localStorage.setItem("jobradar.region", st.region); } catch (e) { /* storage blocked */ }
  }
  function saveHash() {
    var h = new URLSearchParams();
    if (st.stack.length) h.set("stack", st.stack.join(","));
    if (st.region) h.set("region", st.region);
    if (st.unverified) h.set("unverified", "1");
    if (st.mode) h.set("mode", st.mode);
    if (st.years < 11) h.set("years", st.years);
    if (st.levels.length) h.set("levels", st.levels.join(","));
    if (st.comp) h.set("comp", st.comp);
    if (!st.eng) h.set("eng", "0");
    if (st.q) h.set("q", st.q);
    if (st.newOnly) h.set("new", "1");
    var s = h.toString();
    history.replaceState(null, "", s ? "#" + s : location.pathname);
  }
  function loadHash() {
    var h = new URLSearchParams(location.hash.slice(1));
    var saved = ""; try { saved = localStorage.getItem("jobradar.region") || ""; } catch (e) { /* ignore */ }
    $("stack").value = h.get("stack") || "";
    $("region").value = h.has("region") ? h.get("region") : saved;
    $("unverified").checked = h.get("unverified") === "1";
    $("years").value = h.get("years") || 11;
    $("comp").value = h.get("comp") || 0;
    $("eng").checked = h.get("eng") !== "0";
    $("q").value = h.get("q") || "";
    $("newOnly").checked = h.get("new") === "1";
    st.mode = h.get("mode") || "";
    st.levels = (h.get("levels") || "").split(",").filter(Boolean).map(Number);
    syncChips();
  }
  function syncChips() {
    Array.prototype.forEach.call($("mode").children, function (b) { b.classList.toggle("on", b.dataset.v === st.mode); });
    Array.prototype.forEach.call($("levels").children, function (b) { b.classList.toggle("on", st.levels.indexOf(+b.dataset.v) >= 0); });
  }

  // ---------- init
  var counts = {};
  ALL.forEach(function (p) { p.r.forEach(function (r) { counts[r] = (counts[r] || 0) + 1; }); });
  var opts = META.countries.slice().sort(function (a, b) {
    return (COUNTRY_NAMES[a] ? 0 : 1) - (COUNTRY_NAMES[b] ? 0 : 1) || (COUNTRY_NAMES[a] || a).localeCompare(COUNTRY_NAMES[b] || b);
  });
  $("region").insertAdjacentHTML("beforeend", opts.map(function (c) {
    return '<option value="' + c + '">' + esc(COUNTRY_NAMES[c] || c) + " (" + c + ")</option>";
  }).join(""));
  $("vocab").innerHTML = META.vocab.map(function (v) { return '<option value="' + esc(v) + '">'; }).join("");
  $("levels").innerHTML = LEVELS.map(function (l, i) { return '<button type="button" data-v="' + i + '">' + l + "</button>"; }).join("");

  var bs = META.board_status || {};
  $("meta").textContent = "Searching all " + ALL.length.toLocaleString() + " postings from " +
    (META.boards_total || "?") + " boards (" + (bs.ok || 0) + " ok, " + (bs.empty || 0) + " empty, " + (bs.error || 0) +
    " failed). Swept " + (META.finished_at || "").replace("T", " ").slice(0, 16) + " UTC.";

  var deb;
  function onInput() { clearTimeout(deb); deb = setTimeout(function () { readControls(); apply(); }, 90); }
  ["stack", "q"].forEach(function (id) { $(id).addEventListener("input", onInput); });
  ["region", "unverified", "years", "strictYears", "comp", "requireComp", "visa", "eng", "newOnly", "sort"].forEach(function (id) {
    $(id).addEventListener("input", onInput); $(id).addEventListener("change", onInput);
  });
  $("mode").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return; st.mode = b.dataset.v; syncChips(); readControls(); apply();
  });
  $("levels").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return; var v = +b.dataset.v, i = st.levels.indexOf(v);
    if (i >= 0) st.levels.splice(i, 1); else st.levels.push(v); syncChips(); readControls(); apply();
  });
  $("more").addEventListener("click", function () { st.shown += PAGE; render(); });
  $("reset").addEventListener("click", function () { history.replaceState(null, "", location.pathname); loadHash(); $("region").value = ""; readControls(); apply(); });
  $("toggleFilters").addEventListener("click", function () { $("filters").classList.toggle("open"); });

  loadHash(); readControls(); apply();
})();
