(function () {
  var $ = function (id) { return document.getElementById(id); };
  var searchEl = $("search");
  var newBtn = $("new-btn");
  var statusLine = $("status-line");
  var sideTitle = $("side-title");
  var listEl = $("page-list");
  var emptyEl = $("empty");

  var viewEl = $("view");
  var vTitle = $("v-title");
  var vMeta = $("v-meta");
  var vOutline = $("v-outline");
  var vBody = $("v-body");
  var editBtn = $("edit-btn");
  var historyBtn = $("history-btn");

  var editorEl = $("editor");
  var eTitle = $("e-title");
  var eBody = $("e-body");
  var eSummary = $("e-summary");
  var eBase = $("e-base");
  var eConflict = $("e-conflict");
  var eConflictMeta = $("e-conflict-meta");
  var eConflictDiff = $("e-conflict-diff");
  var conflictReload = $("conflict-reload");
  var conflictDiffBtn = $("conflict-diff");
  var saveBtn = $("save-btn");
  var cancelBtn = $("cancel-btn");

  var historyEl = $("history");
  var hTitle = $("h-title");
  var hList = $("h-list");
  var hClose = $("history-close");
  var hDetail = $("h-detail");
  var hDetailMeta = $("h-detail-meta");
  var hDetailBody = $("h-detail-body");

  var newDialog = $("new-dialog");
  var newForm = $("new-form");
  var nTitle = $("n-title");
  var nSlug = $("n-slug");

  var pages = [];
  var current = null; // full page currently shown
  var conflictCurrent = null; // page as it is on the Station after a 409
  var searchTimer = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function relativeTime(ts) {
    if (!ts) return "";
    var sec = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
    if (sec < 60) return sec + "s ago";
    var min = Math.floor(sec / 60);
    if (min < 60) return min + "m ago";
    var hr = Math.floor(min / 60);
    if (hr < 48) return hr + "h ago";
    return Math.floor(hr / 24) + "d ago";
  }

  function slugify(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64)
      .replace(/-+$/g, "");
  }

  function show(panel) {
    emptyEl.hidden = panel !== "empty";
    viewEl.hidden = panel !== "view";
    editorEl.hidden = panel !== "editor";
    historyEl.hidden = panel !== "history";
  }

  // -- minimal Markdown-ish rendering: headings, lists, code fences, paragraphs.
  function renderBody(text) {
    var lines = String(text || "").split("\n");
    var out = [];
    var para = [];
    var list = [];
    var inCode = false;
    var code = [];
    var headingIndex = 0;

    function flushPara() {
      if (para.length) {
        out.push("<p>" + esc(para.join(" ")) + "</p>");
        para = [];
      }
    }
    function flushList() {
      if (list.length) {
        out.push("<ul>" + list.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>");
        list = [];
      }
    }

    lines.forEach(function (line) {
      if (/^```/.test(line)) {
        flushPara();
        flushList();
        if (inCode) {
          out.push("<pre>" + esc(code.join("\n")) + "</pre>");
          code = [];
        }
        inCode = !inCode;
        return;
      }
      if (inCode) {
        code.push(line);
        return;
      }
      var h = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (h) {
        flushPara();
        flushList();
        var level = Math.min(h[1].length + 1, 4);
        out.push('<h' + level + ' id="sec-' + headingIndex + '">' + esc(h[2]) + "</h" + level + ">");
        headingIndex += 1;
        return;
      }
      var li = line.match(/^\s*[-*]\s+(.+)$/);
      if (li) {
        flushPara();
        list.push(li[1]);
        return;
      }
      if (!line.trim()) {
        flushPara();
        flushList();
        return;
      }
      flushList();
      para.push(line.trim());
    });
    if (inCode) out.push("<pre>" + esc(code.join("\n")) + "</pre>");
    flushPara();
    flushList();
    if (!out.length) return '<p class="fb-empty-page">This page is empty. Edit it to add something.</p>';
    return out.join("");
  }

  function renderOutline(outline) {
    var heads = (outline || []).filter(function (s) { return s.heading; });
    if (heads.length < 2) {
      vOutline.hidden = true;
      vOutline.innerHTML = "";
      return;
    }
    vOutline.hidden = false;
    vOutline.innerHTML = heads
      .map(function (s, i) {
        return '<a class="lvl-' + s.level + '" href="#sec-' + i + '">' + esc(s.heading) + "</a>";
      })
      .join("");
  }

  function renderDiff(text) {
    return String(text || "")
      .split("\n")
      .map(function (l) {
        var cls = "";
        if (/^\+(?!\+\+)/.test(l)) cls = "add";
        else if (/^-(?!--)/.test(l)) cls = "del";
        else if (/^@@/.test(l)) cls = "hunk";
        return cls ? '<span class="' + cls + '">' + esc(l) + "</span>" : esc(l);
      })
      .join("\n");
  }

  // -- list / search --------------------------------------------------------

  var lastItems = [];
  var lastIsSearch = false;

  function renderList(items, isSearch) {
    lastItems = items;
    lastIsSearch = isSearch;
    sideTitle.textContent = isSearch ? "Results" : "All pages";
    if (!items.length) {
      listEl.innerHTML =
        '<li class="muted" style="padding:0.5rem">' +
        (isSearch ? "Nothing matches." : "No pages yet. Create the first one.") +
        "</li>";
      return;
    }
    listEl.innerHTML = items
      .map(function (p) {
        var cls = current && current.slug === p.slug ? "active" : "";
        return (
          '<li><button type="button" class="' + cls + '" data-slug="' + esc(p.slug) + '">' +
          '<span class="fb-item-title">' + esc(p.title) + "</span>" +
          '<span class="fb-item-meta">rev ' + p.revision + " · " + esc(p.updated_by) + " · " + relativeTime(p.updated_at) + "</span>" +
          (p.snippet ? '<span class="fb-item-snippet">' + esc(p.snippet) + "</span>" : "") +
          "</button></li>"
        );
      })
      .join("");
    listEl.querySelectorAll("button[data-slug]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openPage(btn.getAttribute("data-slug"));
      });
    });
  }

  function refreshList() {
    return WaypostAuth.api("/api/fieldbook/pages")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        pages = data.pages || [];
        statusLine.textContent =
          (data.count || 0) + " page" + (data.count === 1 ? "" : "s") +
          " · editable community knowledge · every save keeps a revision";
        if (!searchEl.value.trim()) renderList(pages, false);
      })
      .catch(function () {
        statusLine.textContent = "Could not load the Fieldbook.";
      });
  }

  function runSearch() {
    var q = searchEl.value.trim();
    if (!q) {
      renderList(pages, false);
      return;
    }
    WaypostAuth.api("/api/fieldbook/search?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (data) { renderList(data.results || [], true); });
  }

  // -- view -----------------------------------------------------------------

  function openPage(slug, opts) {
    opts = opts || {};
    return WaypostAuth.api("/api/fieldbook/pages/" + encodeURIComponent(slug))
      .then(function (r) {
        if (r.status === 404) throw new Error("not_found");
        return r.json();
      })
      .then(function (page) {
        current = page;
        if (location.hash !== "#" + slug) history.replaceState(null, "", "#" + slug);
        vTitle.textContent = page.title;
        vMeta.textContent =
          "Revision " + page.revision + " · last edited by " + page.updated_by +
          " " + relativeTime(page.updated_at) + " · " + page.size + " chars";
        renderOutline(page.outline);
        vBody.innerHTML = renderBody(page.body);
        show("view");
        renderList(lastItems.length || lastIsSearch ? lastItems : pages, lastIsSearch);
        if (opts.edit) startEdit();
      })
      .catch(function () {
        current = null;
        show("empty");
        emptyEl.textContent = "That page doesn't exist (yet).";
      });
  }

  // -- edit -----------------------------------------------------------------

  function startEdit() {
    if (!current) return;
    conflictCurrent = null;
    eConflict.hidden = true;
    eConflictDiff.hidden = true;
    eTitle.value = current.title;
    eBody.value = current.body;
    eSummary.value = "";
    eBase.textContent = "Editing revision " + current.revision + " of " + current.slug;
    show("editor");
    eBody.focus();
  }

  function save() {
    if (!current) return;
    var title = eTitle.value.trim();
    if (!title) {
      eTitle.focus();
      return;
    }
    saveBtn.disabled = true;
    WaypostAuth.api("/api/fieldbook/pages/" + encodeURIComponent(current.slug), {
      method: "PUT",
      body: JSON.stringify({
        base_revision: current.revision,
        title: title,
        body: eBody.value,
        summary: eSummary.value.trim(),
      }),
    })
      .then(function (r) {
        if (r.status === 409) {
          return r.json().then(function (j) {
            var detail = j.detail || {};
            conflictCurrent = detail.current || null;
            eConflict.hidden = false;
            eConflictDiff.hidden = true;
            eConflictMeta.textContent = conflictCurrent
              ? "Now at revision " + conflictCurrent.revision + ", saved by " +
                conflictCurrent.updated_by + " " + relativeTime(conflictCurrent.updated_at) +
                ". Your text is still here — nothing was overwritten."
              : "";
            throw new Error("conflict");
          });
        }
        if (!r.ok) {
          return r.json().then(function (j) {
            throw new Error(typeof j.detail === "string" ? j.detail : "save failed");
          });
        }
        return r.json();
      })
      .then(function (page) {
        current = page;
        return refreshList().then(function () { return openPage(page.slug); });
      })
      .catch(function (err) {
        if (err.message !== "conflict") alert("Could not save: " + err.message);
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  conflictReload.addEventListener("click", function () {
    if (!conflictCurrent) return;
    current = conflictCurrent;
    startEdit();
  });

  conflictDiffBtn.addEventListener("click", function () {
    if (!current || !conflictCurrent) return;
    WaypostAuth.api(
      "/api/fieldbook/pages/" + encodeURIComponent(current.slug) +
      "/diff?from=" + current.revision + "&to=" + conflictCurrent.revision
    )
      .then(function (r) { return r.json(); })
      .then(function (d) {
        eConflictDiff.hidden = false;
        eConflictDiff.innerHTML = renderDiff(d.diff || "(no textual change)");
      });
  });

  saveBtn.addEventListener("click", save);
  cancelBtn.addEventListener("click", function () {
    if (current) openPage(current.slug);
    else show("empty");
  });
  editBtn.addEventListener("click", startEdit);

  // -- history --------------------------------------------------------------

  function openHistory() {
    if (!current) return;
    hTitle.textContent = "History · " + current.title;
    hDetail.hidden = true;
    WaypostAuth.api("/api/fieldbook/pages/" + encodeURIComponent(current.slug) + "/history")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var revs = data.revisions || [];
        hList.innerHTML = revs
          .map(function (rv) {
            var isCurrent = rv.revision === current.revision;
            return (
              "<li>" +
              '<span class="rev">rev ' + rv.revision + (isCurrent ? " ·now" : "") + "</span>" +
              "<span>" + esc(rv.author) + " · " + relativeTime(rv.created_at) +
              (rv.summary ? ' · <span class="muted">' + esc(rv.summary) + "</span>" : "") +
              "</span>" +
              '<span class="fb-actions">' +
              '<button type="button" class="secondary" data-view="' + rv.revision + '">Read</button>' +
              (isCurrent ? "" : '<button type="button" class="secondary" data-diff="' + rv.revision + '">Compare to now</button>') +
              "</span></li>"
            );
          })
          .join("");
        hList.querySelectorAll("button[data-view]").forEach(function (btn) {
          btn.addEventListener("click", function () { viewRevision(btn.getAttribute("data-view")); });
        });
        hList.querySelectorAll("button[data-diff]").forEach(function (btn) {
          btn.addEventListener("click", function () { diffRevision(btn.getAttribute("data-diff")); });
        });
        show("history");
      });
  }

  function viewRevision(rev) {
    WaypostAuth.api(
      "/api/fieldbook/pages/" + encodeURIComponent(current.slug) + "/revisions/" + rev
    )
      .then(function (r) { return r.json(); })
      .then(function (rv) {
        hDetail.hidden = false;
        hDetailMeta.textContent =
          "Revision " + rv.revision + " · " + rv.author + " · " + relativeTime(rv.created_at) +
          (rv.title !== current.title ? ' · titled "' + rv.title + '"' : "");
        hDetailBody.innerHTML = esc(rv.body);
      });
  }

  function diffRevision(rev) {
    WaypostAuth.api(
      "/api/fieldbook/pages/" + encodeURIComponent(current.slug) + "/diff?from=" + rev
    )
      .then(function (r) { return r.json(); })
      .then(function (d) {
        hDetail.hidden = false;
        hDetailMeta.textContent = "Changes from revision " + d.from_revision + " to " + d.to_revision;
        hDetailBody.innerHTML = renderDiff(d.diff || "(no textual change)");
      });
  }

  historyBtn.addEventListener("click", openHistory);
  hClose.addEventListener("click", function () { if (current) openPage(current.slug); });

  // -- new page -------------------------------------------------------------

  newBtn.addEventListener("click", function () {
    nTitle.value = searchEl.value.trim();
    nSlug.value = slugify(nTitle.value);
    newDialog.showModal();
  });
  nTitle.addEventListener("input", function () {
    if (!nSlug.dataset.touched) nSlug.value = slugify(nTitle.value);
  });
  nSlug.addEventListener("input", function () { nSlug.dataset.touched = "1"; });

  newForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var value = ev.submitter ? ev.submitter.value : "cancel";
    if (value === "cancel") {
      newDialog.close();
      return;
    }
    var title = nTitle.value.trim();
    if (!title) return;
    var slug = nSlug.value.trim() || slugify(title);
    WaypostAuth.api("/api/fieldbook/pages", {
      method: "POST",
      body: JSON.stringify({ title: title, slug: slug, body: "" }),
    })
      .then(function (r) {
        if (r.status === 409) throw new Error("A page already lives at /" + slug + ".");
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || "failed"); });
        return r.json();
      })
      .then(function (page) {
        newDialog.close();
        delete nSlug.dataset.touched;
        searchEl.value = "";
        return refreshList().then(function () { return openPage(page.slug, { edit: true }); });
      })
      .catch(function (err) {
        alert("Could not create page: " + err.message);
      });
  });

  // -- wiring ---------------------------------------------------------------

  searchEl.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 180);
  });

  window.addEventListener("hashchange", function () {
    var slug = location.hash.replace(/^#/, "");
    if (slug && (!current || current.slug !== slug)) openPage(slug);
  });

  refreshList().then(function () {
    var slug = location.hash.replace(/^#/, "");
    if (slug) openPage(slug);
    else if (pages.length) openPage(pages[0].slug);
    else show("empty");
  });
})();
