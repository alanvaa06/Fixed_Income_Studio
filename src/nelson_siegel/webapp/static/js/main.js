/* Fixed Income Studio - bootstrap */
(function (S) {
  "use strict";
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => S.boot());
  } else {
    S.boot();
  }
})(window.Studio);
