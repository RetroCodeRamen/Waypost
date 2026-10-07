(function () {
  var myUsername = "";
  var titleEl = document.getElementById("title");
  var bodyEl = document.getElementById("body");
  var feedEl = document.getElementById("feed");
  var form = document.getElementById("composer");
  var avatarEl = document.getElementById("composer-avatar");
  var refreshBtn = document.getElementById("refresh");
  var filterEl = document.getElementById("filter");
  var viewGroupFieldEl = document.getElementById("view-group-field");
  var viewGroupIdEl = document.getElementById("view-group-id");
  var scopeEl = document.getElementById("scope");
  var groupFieldEl = document.getElementById("group-field");
  var groupIdEl = document.getElementById("group-id");

  function loadGroups() {
    return fetch("/api/groups", { credentials: "same-origin" })
      .then(function (r) {
        return r.ok ? r.json() : { groups: [] };
      })
      .then(function (data) {
        var opts = (data.groups || [])
          .map(function (g) {
            return '<option value="' + esc(g.id) + '">' + esc(g.name) + "</option>";
          })
          .join("");
        groupIdEl.innerHTML = opts;
        viewGroupIdEl.innerHTML = opts;
      });
  }

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
    var url = "/api/commons/posts?limit=50";
    if (filterEl.value === "group" && viewGroupIdEl.value) {
      url += "&group_id=" + encodeURIComponent(viewGroupIdEl.value);
    }
    return fetch(url)
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
    var author = myUsername;
    var body = bodyEl.value.trim();
    if (!author || !body) return;
    var payload = {
      author: author,
      title: titleEl.value.trim(),
      body: body,
    };
    if (scopeEl.value === "group" && groupIdEl.value) {
      payload.group_id = groupIdEl.value;
    }
    fetch("/api/commons/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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

  scopeEl.addEventListener("change", function () {
    groupFieldEl.hidden = scopeEl.value !== "group";
  });
  filterEl.addEventListener("change", function () {
    viewGroupFieldEl.hidden = filterEl.value !== "group";
    refresh();
  });

  refreshBtn.addEventListener("click", function () {
    refresh();
  });

  WaypostAuth.requireAuth().then(function (user) {
    if (!user) return;
    myUsername = user.username;
    if (avatarEl) avatarEl.textContent = initials(myUsername);
    loadGroups().then(refresh);
    setInterval(refresh, 60000);
  });
})();
