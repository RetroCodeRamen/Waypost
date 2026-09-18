(function () {
  var meEl = document.getElementById("me");
  var titleEl = document.getElementById("title");
  var bodyEl = document.getElementById("body");
  var feedEl = document.getElementById("feed");
  var form = document.getElementById("composer");
  var refreshBtn = document.getElementById("refresh");

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

  function initials(name) {
    var p = String(name || "?").trim().split(/[\s@]+/);
    if (p.length === 1) return p[0].slice(0, 2).toUpperCase();
    return (p[0][0] + p[1][0]).toUpperCase();
  }

  function render(posts) {
    if (!posts.length) {
      feedEl.innerHTML =
        '<li class="commons-empty muted">No posts yet. Be the first to share something.</li>';
      return;
    }
    feedEl.innerHTML = posts
      .map(function (p) {
        var title = p.title
          ? '<div class="commons-post__title">' + esc(p.title) + "</div>"
          : "";
        return (
          '<li class="commons-post">' +
          '<div class="commons-post__avatar" aria-hidden="true">' +
          esc(initials(p.author)) +
          "</div>" +
          '<div class="commons-post__body">' +
          '<div class="commons-post__meta">' +
          '<a class="commons-post__author" href="/~' +
          encodeURIComponent(p.author) +
          '">' +
          esc(p.author) +
          "</a>" +
          '<span class="commons-post__time">' +
          esc(relativeTime(p.created_at)) +
          "</span></div>" +
          title +
          '<div class="commons-post__text">' +
          esc(p.body) +
          "</div>" +
          '<div class="commons-post__links">' +
          '<a href="/dispatch.html">Dispatch</a> · ' +
          '<a href="/~' +
          encodeURIComponent(p.author) +
          '">Profile</a>' +
          "</div></div></li>"
        );
      })
      .join("");
  }

  function refresh() {
    return fetch("/api/commons/posts?limit=50")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        render(data.posts || []);
      })
      .catch(function () {
        feedEl.innerHTML =
          '<li class="commons-empty muted">Could not load Commons.</li>';
      });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var author = meEl.value.trim();
    var body = bodyEl.value.trim();
    if (!author || !body) return;
    fetch("/api/commons/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        author: author,
        title: titleEl.value.trim(),
        body: body,
      }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("post failed");
        bodyEl.value = "";
        titleEl.value = "";
        return refresh();
      })
      .catch(function () {
        alert("Could not post.");
      });
  });

  refreshBtn.addEventListener("click", function () {
    refresh();
  });

  refresh();
})();
