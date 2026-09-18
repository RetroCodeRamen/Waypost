(function () {
  var el = document.getElementById("addr");
  if (el) {
    el.textContent = window.location.origin + "/";
  }

  fetch("/api/health")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var tag = document.querySelector(".tagline");
      if (tag && data.ssid) {
        tag.textContent = "Local community network · " + data.ssid;
      }
    })
    .catch(function () { /* offline portal still renders */ });
})();
