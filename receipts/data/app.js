/* receipts desk. Vanilla JS, no build step, no network except its own API. */
(function () {
  "use strict";

  var state = {
    board: null,
    visibleQuotes: [],
    active: -1,
    filter: "",
    theme: null,
    demo: false,
    static: false,
    running: false,
    runId: null,
    pollTimer: null,
    toastTimer: null
  };

  var els = {};

  var IDS = [
    "app", "ask-form", "question", "run", "status", "demo-flag", "progress",
    "progress-fill", "empty", "working", "error", "error-title", "error-message",
    "error-retry", "board", "run-id", "stat-sources", "stat-quotes", "stat-domains",
    "stat-seconds", "kinds", "themes", "failures", "failure-count", "quote-count", "filter",
    "quotes", "quote-empty", "source-count", "sources", "exportbar", "export-md",
    "export-html", "export-json", "strip", "toast"
  ];

  function cacheDom() {
    IDS.forEach(function (id) {
      els[id.replace(/-/g, "_")] = document.getElementById(id);
    });
  }

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) { node.removeChild(node.firstChild); }
  }

  function safeUrl(value) {
    try {
      var url = new URL(String(value), window.location.href);
      if (url.protocol === "http:" || url.protocol === "https:") { return url.href; }
    } catch (error) { /* not a URL */ }
    return null;
  }

  function plural(count, one, many) {
    return count === 1 ? one : many;
  }

  function sourceIndex(board) {
    var map = {};
    (board.sources || []).forEach(function (source) { map[source.id] = source; });
    return map;
  }

  function setStatus(text) {
    if (els.status) { els.status.textContent = text; }
  }

  function setProgress(percent) {
    var value = Math.max(0, Math.min(100, Math.round(percent)));
    if (els.progress_fill) { els.progress_fill.style.width = value + "%"; }
    if (els.progress) { els.progress.setAttribute("aria-valuenow", String(value)); }
  }

  function notice(message) {
    if (!els.toast) { return; }
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { els.toast.hidden = true; }, 2400);
  }

  function setRunning(running) {
    state.running = running;
    if (els.run) {
      els.run.disabled = running;
      els.run.textContent = running ? "Running" : (state.static ? "Static" : "Run");
    }
    if (!state.static) {
      document.querySelectorAll('input[name="source"]').forEach(function (input) {
        input.disabled = running;
      });
    }
  }

  function hideStates() {
    els.empty.hidden = true;
    els.working.hidden = true;
    els.error.hidden = true;
    els.board.hidden = true;
    els.exportbar.hidden = true;
  }

  function showEmpty() {
    hideStates();
    els.empty.hidden = false;
    clear(els.quotes);
    clear(els.sources);
    clear(els.themes);
    clear(els.failures);
    state.board = null;
    state.visibleQuotes = [];
    state.active = -1;
    state.theme = null;
    if (els.filter) { els.filter.value = ""; }
    state.filter = "";
    els.strip.textContent = "No board yet. Ask a question above.";
    setStatus("Waiting for a question.");
    setProgress(0);
    document.title = "receipts · the research desk with no author";
    setRunning(false);
  }

  function showWorking() {
    hideStates();
    els.working.hidden = false;
    els.strip.textContent = "A run is in progress. The board appears when the pages are in.";
    setProgress(4);
  }

  function showError(title, message) {
    hideStates();
    els.error.hidden = false;
    els.error_title.textContent = title;
    els.error_message.textContent = message || "Unknown error.";
    els.strip.textContent = "No board. The failure is above.";
    setStatus("Run stopped.");
    setProgress(0);
    setRunning(false);
    document.title = "receipts · run stopped";
  }

  function setDemoMode() {
    state.demo = true;
    els.demo_flag.hidden = false;
    els.demo_flag.textContent = "demo board";
  }

  function setStaticMode() {
    state.static = true;
    els.demo_flag.hidden = false;
    els.demo_flag.textContent = "static board";
    els.exportbar.hidden = true;
    var input = els.question;
    input.readOnly = true;
    input.placeholder = "Static board. Every sentence is a quote.";
    input.setAttribute("aria-label", "Static board");
  }

  /* ------------------------------------------------------------- rendering */

  function renderBoard(board) {
    if (!board || !board.coverage) {
      showError("Empty board", "The server returned a board without coverage.");
      return;
    }
    state.board = board;
    state.active = -1;
    state.theme = null;
    state.runId = board.id;
    hideStates();
    els.board.hidden = false;
    els.exportbar.hidden = state.static;
    if (state.demo || state.static) {
      els.question.value = board.question || "";
    }

    els.run_id.textContent = board.id || "";
    els.stat_sources.textContent = String((board.sources || []).length);
    els.stat_quotes.textContent = String((board.quotes || []).length);
    var domains = {};
    (board.sources || []).forEach(function (source) { if (source.domain) { domains[source.domain] = 1; } });
    els.stat_domains.textContent = String(Object.keys(domains).length);
    els.stat_seconds.textContent = Number(board.seconds || 0).toFixed(1);

    renderKinds(board);
    renderThemes(board);
    renderFailures(board);
    renderSources(board);
    renderQuotes();

    var coverage = board.coverage;
    setStatus(
      coverage.queries + " queries · " + coverage.hits + " results · " +
      coverage.pages_ok + " pages ok / " + coverage.pages_failed + " blocked · " +
      coverage.quotes + " quotes"
    );
    els.strip.textContent = footerText(board);
    setProgress(100);
    setRunning(false);
    document.title = "receipts · " + board.question;

    var kinds = {};
    (board.sources || []).forEach(function (source) { kinds[source.kind] = 1; });
    document.querySelectorAll('input[name="source"]').forEach(function (input) {
      input.checked = Boolean(kinds[input.value]);
      if (state.static) { input.disabled = true; }
    });

    if (state.static) {
      setStatus("static board · every sentence is a quote · " + board.quotes.length + " quotes");
    } else if (state.demo) {
      var baked = String(board.finished_at || board.started_at || "").slice(0, 10);
      setStatus("demo board · " + board.quotes.length + " quotes · baked " + baked);
    }
  }

  function footerText(board) {
    var c = board.coverage;
    var text = c.quotes + " " + plural(c.quotes, "quote", "quotes") + " from " +
      c.pages_ok + " " + plural(c.pages_ok, "page", "pages") + " and " +
      c.queries + " " + plural(c.queries, "query", "queries") + ". ";
    if (c.pages_failed > 0) {
      text += c.pages_failed + " " + plural(c.pages_failed, "page was", "pages were") +
        " blocked and " + plural(c.pages_failed, "is", "are") + " listed in Coverage. ";
    } else {
      text += "No pages were blocked. ";
    }
    text += "Nothing here was generated.";
    return text;
  }

  function renderKinds(board) {
    clear(els.kinds);
    var order = ["web", "news", "reddit", "hn", "wiki", "arxiv"];
    var groups = {};
    (board.sources || []).forEach(function (source) {
      if (!groups[source.kind]) { groups[source.kind] = []; }
      groups[source.kind].push(source);
    });
    var kinds = order.filter(function (kind) { return groups[kind]; });
    Object.keys(groups).forEach(function (kind) {
      if (kinds.indexOf(kind) === -1) { kinds.push(kind); }
    });
    if (!kinds.length) {
      els.kinds.appendChild(make("li", "panel-note", "No source rows."));
      return;
    }
    kinds.forEach(function (kind) {
      var sources = groups[kind];
      var row = make("li", "kind-row");
      row.appendChild(make("span", "kind-name", kind));
      var dots = make("span", "kind-dots");
      sources.forEach(function (source) {
        var dot = make("span", "status-dot " + (source.status || "ok"));
        dot.title = (source.domain || kind) + ": " + (source.status || "ok");
        dot.setAttribute("aria-label", (source.domain || kind) + ": " + (source.status || "ok"));
        dots.appendChild(dot);
      });
      row.appendChild(dots);
      var ok = sources.filter(function (source) {
        return source.status === "ok" || source.status === "thin";
      }).length;
      row.appendChild(make("span", "kind-count", ok + "/" + sources.length));
      els.kinds.appendChild(row);
    });
  }

  function renderThemes(board) {
    clear(els.themes);
    var themes = board.themes || [];
    if (!themes.length) {
      els.themes.appendChild(make("p", "panel-note", "No term repeats across two quotes."));
      return;
    }
    themes.forEach(function (theme) {
      var button = make("button", "theme");
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.theme === theme.term));
      button.appendChild(document.createTextNode(theme.term));
      button.appendChild(make("b", null, theme.count));
      button.title = "Show the " + theme.count + " quotes that share this term";
      button.addEventListener("click", function () {
        state.theme = state.theme === theme.term ? null : theme.term;
        updateThemePressed();
        renderQuotes();
      });
      els.themes.appendChild(button);
    });
  }

  function updateThemePressed() {
    els.themes.querySelectorAll(".theme").forEach(function (button) {
      var term = button.firstChild ? button.firstChild.textContent : "";
      button.setAttribute("aria-pressed", String(term === state.theme));
    });
  }

  function renderFailures(board) {
    clear(els.failures);
    var failures = board.failures || [];
    els.failure_count.textContent = failures.length ? "(" + failures.length + ")" : "(0)";
    if (!failures.length) {
      var none = make("li", "failure-none", "No failures. Every request produced a page.");
      els.failures.appendChild(none);
      return;
    }
    failures.forEach(function (failure) {
      var item = make("li");
      var label = failure.reason || "failed";
      if (failure.stage) { label += " · " + failure.stage; }
      item.appendChild(make("span", "failure-reason", label));
      if (failure.url) {
        var url = safeUrl(failure.url);
        if (url) {
          var anchor = make("a", "failure-url", failure.url);
          anchor.href = url;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          item.appendChild(anchor);
        } else {
          item.appendChild(make("span", "failure-url", failure.url));
        }
      }
      els.failures.appendChild(item);
    });
  }

  function renderSources(board) {
    clear(els.sources);
    var sources = board.sources || [];
    els.source_count.textContent = String(sources.length);
    var failures = {};
    (board.failures || []).forEach(function (failure) {
      if (failure.url) { failures[failure.url] = failure; }
    });
    sources.forEach(function (source) {
      var item = make("li");
      var top = make("div", "source-top");
      top.appendChild(make("span", "kind", source.kind || "?"));
      var dot = make("span", "status-dot " + (source.status || "ok"));
      dot.title = source.status || "ok";
      dot.setAttribute("aria-label", "Status: " + (source.status || "ok"));
      top.appendChild(dot);
      item.appendChild(top);

      var url = safeUrl(source.url);
      var title = source.title || source.domain || source.url || "Untitled source";
      var titleNode;
      if (url) {
        titleNode = make("a", "source-title", title);
        titleNode.href = url;
        titleNode.target = "_blank";
        titleNode.rel = "noopener noreferrer";
      } else {
        titleNode = make("span", "source-title", title);
      }
      item.appendChild(titleNode);

      var meta = make("div", "source-meta");
      meta.appendChild(make("span", null, source.domain || ""));
      meta.appendChild(make("span", "sep", "·"));
      meta.appendChild(make("span", null, source.date || "date n/a"));
      meta.appendChild(make("span", "sep", "·"));
      meta.appendChild(make("span", "source-quotes", (source.quotes || 0) + " " + plural(source.quotes || 0, "quote", "quotes")));
      item.appendChild(meta);

      if (source.status && source.status !== "ok" && source.status !== "thin") {
        var failure = failures[source.url];
        var reason = failure ? failure.reason : (source.status + " before a quote");
        item.appendChild(make("div", "source-reason", reason));
      } else if (source.status === "thin") {
        item.appendChild(make("div", "source-reason", "only title or description found"));
      }
      els.sources.appendChild(item);
    });
  }

  function themeIds(board) {
    if (!state.theme) { return null; }
    var found = (board.themes || []).filter(function (theme) { return theme.term === state.theme; })[0];
    return found ? found.quotes : [];
  }

  function renderQuotes() {
    var board = state.board;
    if (!board) { return; }
    var byId = sourceIndex(board);
    var allowed = themeIds(board);
    var needle = state.filter;
    var visible = (board.quotes || []).filter(function (quote) {
      if (allowed && allowed.indexOf(quote.id) === -1) { return false; }
      if (!needle) { return true; }
      var source = byId[quote.source_id] || {};
      var haystack = (quote.text + " " + (source.domain || "") + " " + (source.title || "") + " " + (source.via || "")).toLowerCase();
      return haystack.indexOf(needle) !== -1;
    });
    state.visibleQuotes = visible;
    state.active = -1;
    clear(els.quotes);
    els.quote_count.textContent = visible.length === (board.quotes || []).length
      ? String(visible.length)
      : visible.length + " of " + (board.quotes || []).length;

    if (!visible.length) {
      els.quote_empty.hidden = false;
      els.quote_empty.textContent = (board.quotes || []).length
        ? "No quote matches that filter."
        : "No sentence met the quote rules. The failures are listed in Coverage.";
      return;
    }
    els.quote_empty.hidden = true;

    var fragment = document.createDocumentFragment();
    visible.forEach(function (quote, index) {
      var source = byId[quote.source_id] || {};
      var card = make("article", "quote-card");
      card.setAttribute("role", "listitem");
      card.tabIndex = 0;
      card.dataset.index = String(index);
      card.setAttribute("aria-label", "Quote " + (index + 1) + " of " + visible.length);
      card.appendChild(make("blockquote", "quote", quote.text));

      var receipt = make("div", "receipt");
      receipt.appendChild(make("span", "dash", "—"));
      var url = safeUrl(source.url);
      if (url) {
        var link = make("a", null, source.domain || "source");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = source.title || source.url;
        receipt.appendChild(link);
      } else {
        receipt.appendChild(make("span", null, source.domain || "source"));
      }
      receipt.appendChild(make("span", "sep", "·"));
      var date = make("time", null, source.date || "date n/a");
      if (source.date) { date.dateTime = source.date; }
      receipt.appendChild(date);
      receipt.appendChild(make("span", "sep", "·"));
      receipt.appendChild(make("span", "via", "via “" + (source.via || "") + "”"));

      var copy = make("button", "copy", "copy");
      copy.type = "button";
      copy.setAttribute("aria-label", "Copy quote " + (index + 1));
      copy.addEventListener("click", function (event) {
        event.stopPropagation();
        setActive(index, false);
        copyQuote(index);
      });
      receipt.appendChild(copy);
      card.appendChild(receipt);

      card.addEventListener("click", function (event) {
        if (event.target.closest("a, button")) { return; }
        setActive(index, false);
      });
      card.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          setActive(index, false);
          copyQuote(index);
        }
      });
      fragment.appendChild(card);
    });
    els.quotes.appendChild(fragment);
  }

  function setActive(index, focusCard) {
    var cards = els.quotes.querySelectorAll(".quote-card");
    if (!cards.length) { return; }
    if (index < 0) { index = 0; }
    if (index >= cards.length) { index = cards.length - 1; }
    cards.forEach(function (card) { card.classList.remove("is-active"); });
    var card = cards[index];
    card.classList.add("is-active");
    state.active = index;
    if (focusCard) {
      card.focus({ preventScroll: true });
      card.scrollIntoView({ block: "nearest" });
    }
  }

  function moveActive(delta) {
    if (!state.visibleQuotes.length) { return; }
    var next = state.active < 0 ? (delta > 0 ? 0 : state.visibleQuotes.length - 1) : state.active + delta;
    setActive(next, true);
  }

  function copyText(text) {
    return new Promise(function (resolve) {
      var fallback = function () {
        try {
          var area = document.createElement("textarea");
          area.value = text;
          area.setAttribute("readonly", "");
          area.style.position = "fixed";
          area.style.top = "-1000px";
          document.body.appendChild(area);
          area.select();
          var ok = document.execCommand("copy");
          area.remove();
          resolve(Boolean(ok));
        } catch (error) {
          resolve(false);
        }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { resolve(true); }, fallback);
      } else {
        fallback();
      }
    });
  }

  function copyQuote(index) {
    var quote = state.visibleQuotes[index];
    if (!quote) { return; }
    copyText(quote.text).then(function (ok) {
      notice(ok ? "quote copied" : "copy failed, select the text instead");
    });
  }

  /* ---------------------------------------------------------------- runs */

  function selectedSources() {
    return Array.prototype.slice.call(document.querySelectorAll('input[name="source"]:checked'))
      .map(function (input) { return input.value; });
  }

  function startRun() {
    if (state.static) {
      notice("Static export. Install receipts and run the CLI for a live board.");
      return;
    }
    if (state.demo) {
      notice("This is a baked demo board. Run `receipts serve` for a live run.");
      return;
    }
    if (state.running) { return; }
    var question = (els.question.value || "").trim();
    if (!question) {
      els.question.focus();
      notice("Type a question first.");
      return;
    }
    var sources = selectedSources();
    if (!sources.length) {
      notice("Pick at least one source.");
      return;
    }
    hideStates();
    showWorking();
    setRunning(true);
    setStatus("Starting a run.");
    clearTimeout(state.pollTimer);

    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, sources: sources, depth: 2 })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) { throw new Error(data && data.error ? data.error : "HTTP " + response.status); }
        return data;
      });
    }).then(function (data) {
      state.runId = data.id;
      poll(data.id);
    }).catch(function (error) {
      showError("Could not start the run", error.message);
    });
  }

  function poll(id) {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(function () {
      fetch("/api/runs/" + encodeURIComponent(id)).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) { throw new Error(data && data.error ? data.error : "HTTP " + response.status); }
          return data;
        });
      }).then(function (data) {
        if (data.status === "running") {
          updateProgress(data.progress || {});
          poll(id);
          return;
        }
        if (data.status === "done") {
          renderBoard(data.board);
          return;
        }
        throw new Error(data.error || "The run failed.");
      }).catch(function (error) {
        showError("The run stopped", error.message);
      });
    }, 400);
  }

  function updateProgress(progress) {
    var queries = progress.queries || 0;
    var queryTotal = progress.queries_total || 0;
    var ok = progress.pages_ok || 0;
    var failed = progress.pages_failed || 0;
    var pagesTotal = progress.pages_total || 0;
    var parts = [];
    parts.push(queryTotal ? "queries " + queries + " / " + queryTotal : "queries " + queries);
    parts.push("results " + (progress.hits || 0));
    parts.push("pages " + ok + " ok / " + failed + " blocked");
    if (progress.stage === "fetching" || progress.stage === "done") {
      parts.push("quotes " + (progress.quotes || 0));
    }
    setStatus(parts.join(" · "));
    var percent = 4;
    if (progress.stage === "searching") {
      percent = 6 + 44 * (queryTotal ? Math.min(1, queries / queryTotal) : 0);
    } else if (progress.stage === "fetching") {
      percent = 50 + 42 * (pagesTotal ? Math.min(1, (ok + failed) / pagesTotal) : 0);
    } else if (progress.stage === "done") {
      percent = 100;
    }
    setProgress(percent);
  }

  function downloadExport(fmt) {
    if (state.static) {
      notice("The static file carries its own JSON. Use the CLI for Markdown or HTML.");
      return;
    }
    if (!state.board) { return; }
    var href = state.demo
      ? "/api/demo/export?fmt=" + encodeURIComponent(fmt)
      : "/api/runs/" + encodeURIComponent(state.board.id) + "/export?fmt=" + encodeURIComponent(fmt);
    var anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  /* -------------------------------------------------------------- events */

  function bindEvents() {
    els.ask_form.addEventListener("submit", function (event) {
      event.preventDefault();
      startRun();
    });
    els.run.addEventListener("click", startRun);

    document.querySelectorAll(".sample").forEach(function (button) {
      button.addEventListener("click", function () {
        els.question.value = button.dataset.q || "";
        startRun();
      });
    });

    els.filter.addEventListener("input", function () {
      state.filter = (els.filter.value || "").trim().toLowerCase();
      renderQuotes();
    });
    els.filter.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        els.filter.value = "";
        state.filter = "";
        renderQuotes();
        els.filter.blur();
      }
    });

    [els.export_md, els.export_html, els.export_json].forEach(function (button) {
      if (!button) { return; }
      button.addEventListener("click", function () { downloadExport(button.dataset.fmt); });
    });

    els.error_retry.addEventListener("click", startRun);

    document.addEventListener("keydown", function (event) {
      if (event.metaKey || event.ctrlKey || event.altKey) { return; }
      var tag = (event.target.tagName || "").toLowerCase();
      var typing = tag === "input" || tag === "textarea" || event.target.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        els.filter.focus();
        return;
      }
      if (typing || !state.board) { return; }
      if (event.key === "j") {
        event.preventDefault();
        moveActive(1);
      } else if (event.key === "k") {
        event.preventDefault();
        moveActive(-1);
      } else if (event.key === "c" && state.active >= 0) {
        event.preventDefault();
        copyQuote(state.active);
      }
    });
  }

  /* ----------------------------------------------------------------- boot */

  function getJSON(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) {
          throw new Error(data && data.error ? data.error : "HTTP " + response.status);
        }
        return data;
      });
    });
  }

  function boot() {
    cacheDom();
    bindEvents();
    try {
      var forced = new URLSearchParams(window.location.search).get("theme");
      if (forced === "light" || forced === "dark") {
        document.documentElement.setAttribute("data-theme", forced);
      }
    } catch (error) { /* very old browser, use the system theme */ }
    var embedded = window.__RECEIPTS_BOARD__;
    if (window.__RECEIPTS_STATIC__ && embedded) {
      setStaticMode();
      renderBoard(embedded);
      return;
    }
    getJSON("/api/config").then(function (config) {
      if (config && config.demo) {
        setDemoMode();
        return getJSON("/api/demo").then(function (board) {
          if (!board) { throw new Error("The baked board is missing."); }
          renderBoard(board);
        });
      }
      showEmpty();
      return null;
    }).catch(function (error) {
      if (state.demo || state.board) {
        showError("Demo board unavailable", error.message);
        return;
      }
      showError(
        "No desk server",
        "This page needs receipts serve or receipts demo. " +
        "A static export carries its own board and works from disk. (" + error.message + ")"
      );
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
