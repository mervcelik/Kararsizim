(function () {
  "use strict";

  var form = document.querySelector("[data-poll-form]");
  if (!form) return;

  var min = parseInt(form.dataset.min, 10);
  var max = parseInt(form.dataset.max, 10);
  var addButton = form.querySelector("[data-option-add]");
  var rows = Array.prototype.slice.call(form.querySelectorAll("[data-option-row]"));
  var inputs = rows.map(function (row) { return row.querySelector("input"); });

  // Rows keep their DOM order (and colour) — showing N options means showing the first N rows.
  function show(count) {
    rows.forEach(function (row, index) {
      row.hidden = index >= count;
      row.querySelector("[data-option-remove]").hidden = index >= count || count <= min;
    });
    addButton.hidden = false;
    addButton.disabled = count >= max;
  }

  function visibleCount() {
    return rows.filter(function (row) { return !row.hidden; }).length;
  }

  // Without JS all rows stay visible and empty ones are ignored by the server.
  var lastFilled = -1;
  inputs.forEach(function (input, index) { if (input.value.trim()) lastFilled = index; });
  show(Math.max(min, lastFilled + 1));

  addButton.addEventListener("click", function () {
    var count = visibleCount();
    if (count >= max) return;
    show(count + 1);
    inputs[count].focus();
  });

  form.addEventListener("click", function (event) {
    var button = event.target.closest("[data-option-remove]");
    if (!button) return;
    var count = visibleCount();
    if (count <= min) return;
    var removed = rows.indexOf(button.closest("[data-option-row]"));
    for (var i = removed; i < count - 1; i++) inputs[i].value = inputs[i + 1].value;
    inputs[count - 1].value = "";
    show(count - 1);
    inputs[Math.min(removed, count - 2)].focus();
  });
})();
