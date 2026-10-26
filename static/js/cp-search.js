/**
 * Case-insensitive search helpers (Azerbaijani İ/I/ı aware).
 * Keep in sync with apps/core/search.py fold_search().
 */
(function (global) {
  function foldSearch(value) {
    return String(value || "")
      .replace(/İ/g, "i")
      .replace(/I/g, "i")
      .replace(/ı/g, "i")
      .toLocaleLowerCase("az")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function haystackMatch(haystack, query) {
    var q = foldSearch(query);
    if (!q) return true;
    return foldSearch(haystack).indexOf(q) !== -1;
  }

  function rowHaystack(row) {
    return [
      row.getAttribute("data-search"),
      row.getAttribute("data-name"),
      row.getAttribute("data-card"),
      row.getAttribute("data-company"),
      row.getAttribute("data-slug"),
      row.getAttribute("data-email"),
    ]
      .filter(Boolean)
      .join(" ");
  }

  function matchingRows(input, selector) {
    var query = foldSearch(input.value);
    if (!query) return [];
    var root = input.closest("main") || document;
    var starts = [];
    var contains = [];
    Array.prototype.forEach.call(root.querySelectorAll(selector), function (row) {
      var hay = foldSearch(rowHaystack(row) || row.textContent);
      if (!hay) return;
      if (hay.indexOf(query) === 0) starts.push(row);
      else if (hay.indexOf(query) !== -1) contains.push(row);
    });
    return starts.concat(contains);
  }

  function openRow(row) {
    var link = row.tagName === "A" ? row : row.querySelector("a[href]");
    if (link && link.href) {
      window.location = link.href;
      return true;
    }
    row.click();
    return true;
  }

  function selectComboboxOption(input) {
    var box = input.closest(".cp-combobox");
    if (!box) return false;
    var list = box.querySelector(".cp-combobox-list");
    if (!list || list.hidden) return false;
    if (!foldSearch(input.value)) return false;
    var options = list.querySelectorAll("[role='option']");
    if (!options.length) return false;
    var active = list.querySelector("[role='option'].is-active") || options[0];
    active.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    return true;
  }

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key !== "Enter" || event.repeat) return;
      var input = event.target;
      if (!input || input.tagName !== "INPUT") return;
      if (input.readOnly || input.disabled) return;

      if (input.closest(".cp-combobox")) {
        if (selectComboboxOption(input)) {
          event.preventDefault();
          event.stopPropagation();
        }
        return;
      }

      var selector = input.getAttribute("data-enter-select");
      if (!selector) return;
      var rows = matchingRows(input, selector);
      if (!rows.length) return;
      event.preventDefault();
      event.stopPropagation();
      openRow(rows[0]);
    },
    true
  );

  global.cpFoldSearch = foldSearch;
  global.cpHaystackMatch = haystackMatch;
})(typeof window !== "undefined" ? window : this);
