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

  global.cpFoldSearch = foldSearch;
  global.cpHaystackMatch = haystackMatch;
})(typeof window !== "undefined" ? window : this);
