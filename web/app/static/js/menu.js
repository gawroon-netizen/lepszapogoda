// Menu under the logo: <details> opens and closes it without JS; this only closes it on an outside click or Esc.
(function () {
  "use strict";
  var menu = document.querySelector("details.brand");
  if (!menu) return;
  document.addEventListener("click", function (e) {
    if (menu.open && !menu.contains(e.target)) menu.open = false;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
})();
