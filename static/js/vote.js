(function () {
  "use strict";

  var form = document.querySelector("[data-vote-form]");
  if (!form) return;

  var list = form.querySelector("[data-option-list]");
  var decision = document.querySelector("[data-decision]");

  function csrfToken() {
    return form.querySelector("input[name=csrfmiddlewaretoken]").value;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderDecision(results) {
    var wrapper = el("div", "decision");
    var bar;
    if (results.results_visible && results.total) {
      bar = el("div", "decision-bar");
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", results.options.map(function (o) { return o.text + " %" + o.percent; }).join(", "));
      results.options.forEach(function (option) {
        if (!option.percent) return;
        var seg = el("span", "decision-bar__seg decision-bar__seg--" + option.position);
        seg.style.width = option.percent + "%";
        bar.appendChild(seg);
      });
    } else {
      bar = el("div", "decision-bar decision-bar--neutral");
      bar.setAttribute("aria-hidden", "true");
    }
    var meta = el("div", "decision__meta");
    meta.appendChild(el("span", "badge badge--" + results.badge.kind, results.badge.text));
    meta.appendChild(el("span", "decision__total", results.total + " kişi oy verdi"));
    wrapper.appendChild(bar);
    wrapper.appendChild(meta);
    decision.replaceChildren(wrapper);
  }

  function renderOptions(results) {
    var fills = [];
    var rows = results.options.map(function (option) {
      var voted = option.id === results.voted_option_id;
      var row = el("li", "option-row option-row--" + option.position + " option-row--result" + (voted ? " option-row--voted" : ""));
      var inner = el("div", "option-row__inner");
      var fill = el("span", "option-row__fill");
      fill.setAttribute("aria-hidden", "true");
      fill.style.width = "0%";
      fills.push([fill, option.percent]);
      var text = el("span", "option-row__text", option.text);
      if (voted) {
        var check = el("span", "option-row__check", " ✓");
        check.appendChild(el("span", "visually-hidden", " senin oyun"));
        text.appendChild(check);
      }
      inner.appendChild(fill);
      inner.appendChild(text);
      inner.appendChild(el("span", "option-row__percent", "%" + option.percent));
      row.appendChild(inner);
      return row;
    });
    list.replaceChildren.apply(list, rows);
    var hint = form.querySelector("[data-vote-hint]");
    if (hint) hint.remove();
    // Start at 0% and let the CSS transition fill each bar.
    void list.offsetWidth;
    fills.forEach(function (pair) { pair[0].style.width = pair[1] + "%"; });
  }

  function setBusy(busy) {
    form.setAttribute("aria-busy", busy ? "true" : "false");
    list.querySelectorAll("button").forEach(function (button) { button.disabled = busy; });
  }

  form.addEventListener("submit", function (event) {
    var button = event.submitter;
    if (!button || button.name !== "option_id") return;
    event.preventDefault();

    var body = new FormData(form);
    body.set("option_id", button.value);
    setBusy(true);

    fetch(form.action, {
      method: "POST",
      body: body,
      headers: { "Accept": "application/json", "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        var results = result.data.results;
        setBusy(false);
        if (results && results.results_visible) {
          renderDecision(results);
          renderOptions(results);
        }
        if (!result.ok) window.showToast(result.data.message);
      })
      .catch(function () {
        setBusy(false);
        window.showToast("Oy gönderilemedi. Bağlantını kontrol edip tekrar dene.");
      });
  });
})();
