(function () {
  "use strict";

  // Progressive enhancement: without JS the link simply opens the next page.
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-feed-more]");
    if (!link) return;
    event.preventDefault();
    link.setAttribute("aria-busy", "true");
    link.textContent = "Yükleniyor…";

    fetch(link.href, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        return response.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var feed = document.querySelector("[data-feed]");
        var firstNew = null;
        doc.querySelectorAll("[data-feed] [data-poll-card]").forEach(function (card) {
          var imported = document.importNode(card, true);
          feed.appendChild(imported);
          if (!firstNew) firstNew = imported;
        });
        var nextLink = doc.querySelector("[data-feed-more]");
        if (nextLink) {
          link.href = nextLink.getAttribute("href");
          link.textContent = "Daha fazla göster";
          link.removeAttribute("aria-busy");
        } else {
          link.closest(".feed-more").remove();
        }
        if (firstNew) firstNew.querySelector("a").focus({ preventScroll: true });
      })
      .catch(function () {
        window.location.href = link.href;
      });
  });
})();
