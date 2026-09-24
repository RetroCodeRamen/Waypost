(function () {
  var searchEl = document.getElementById("search");
  var resultsEl = document.getElementById("results");
  var statusEl = document.getElementById("status-line");
  var emptyEl = document.getElementById("empty-state");
  var searchTimer = null;

  var SERVICE_LABEL = {
    commons: "Commons",
    noticeboard: "Noticeboard",
    fieldbook: "Fieldbook",
    locker: "Locker",
  };

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

  function render(results) {
    emptyEl.hidden = results.length > 0;
    if (!results.length) {
      resultsEl.innerHTML = "";
      return;
    }
    resultsEl.innerHTML = results
      .map(function (r) {
        return (
          '<li class="finder-item">' +
          '<a href="' + esc(r.url) + '">' +
          '<span class="finder-badge finder-badge--' + esc(r.service) + '">' +
          esc(SERVICE_LABEL[r.service] || r.service) + "</span>" +
          '<span class="finder-item__title">' + esc(r.title || "(untitled)") + "</span>" +
          '<span class="finder-item__meta">' + relativeTime(r.updated_at) + "</span>" +
          (r.snippet ? '<span class="finder-item__snippet">' + esc(r.snippet) + "</span>" : "") +
          "</a></li>"
        );
      })
      .join("");
  }

  function runSearch() {
    var q = searchEl.value.trim();
    if (!q) {
      resultsEl.innerHTML = "";
      emptyEl.hidden = false;
      emptyEl.textContent = "Type to search.";
      statusEl.textContent = "Searches Commons, Noticeboard, Fieldbook, and Locker — only what you can already see in each.";
      return;
    }
    statusEl.textContent = "Searching…";
    fetch("/api/finder/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var results = data.results || [];
        statusEl.textContent = results.length + " result(s) for “" + q + "”.";
        emptyEl.textContent = "Nothing found.";
        render(results);
      })
      .catch(function () {
        statusEl.textContent = "Could not search.";
      });
  }

  searchEl.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 180);
  });

  searchEl.focus();
})();
