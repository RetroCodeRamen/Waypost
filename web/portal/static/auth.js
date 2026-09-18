/** Waypost auth helpers — session cookie + optional Bearer token for Pocket. */
(function (global) {
  var TOKEN_KEY = "waypost_token";

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function setToken(token) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }

  function authHeaders(extra) {
    var h = Object.assign({ "Content-Type": "application/json" }, extra || {});
    var t = getToken();
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  function me() {
    return fetch("/api/auth/me", {
      credentials: "same-origin",
      headers: authHeaders(),
    }).then(function (r) {
      if (r.status === 401) return null;
      return r.json().then(function (j) {
        return j.user || null;
      });
    });
  }

  function requireAuth() {
    return me().then(function (user) {
      if (user) return user;
      var next = encodeURIComponent(location.pathname + location.search);
      location.href = "/login.html?next=" + next;
      return null;
    });
  }

  function logout() {
    return fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
    }).finally(function () {
      setToken("");
      location.href = "/login.html";
    });
  }

  /** fetch wrapper: credentials + Bearer */
  function api(url, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.headers = authHeaders(opts.headers || {});
    return fetch(url, opts);
  }

  global.WaypostAuth = {
    getToken: getToken,
    setToken: setToken,
    authHeaders: authHeaders,
    me: me,
    requireAuth: requireAuth,
    logout: logout,
    api: api,
  };
})(window);
