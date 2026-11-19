(function () {
  "use strict";

  var DURATION_MS = 3000;

  function dismiss(toast) {
    toast.classList.add("toast--hiding");
    window.setTimeout(function () { toast.remove(); }, 200);
  }

  function schedule(toast) {
    window.setTimeout(function () { dismiss(toast); }, DURATION_MS);
  }

  window.showToast = function (text) {
    var region = document.querySelector("[data-toast-region]");
    if (!region) return;
    var toast = document.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.textContent = text;
    region.appendChild(toast);
    schedule(toast);
  };

  document.querySelectorAll("[data-toast]").forEach(schedule);
})();
