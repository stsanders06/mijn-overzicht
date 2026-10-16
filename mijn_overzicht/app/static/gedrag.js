document.querySelectorAll(".toast-weg").forEach(function (knop) {
  knop.addEventListener("click", function () { knop.parentElement.remove(); });
});
document.addEventListener("submit", function (event) {
  var knop = event.submitter;
  var vraag = knop && knop.getAttribute("data-bevestig");
  if (vraag && !window.confirm(vraag)) event.preventDefault();
});
document.querySelectorAll("input[type=file]").forEach(function (veld) {
  veld.addEventListener("change", function () {
    var namen = Array.prototype.map.call(veld.files || [], function (bestand) { return bestand.name; });
    var doel = veld.parentElement.querySelector(".bestandsnamen");
    if (doel) doel.textContent = namen.join(", ");
  });
});
function sluit_meer() {
  document.querySelectorAll("details.meer[open]").forEach(function (menu) {
    menu.open = false;
  });
}
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape") sluit_meer();
});
document.addEventListener("click", function (event) {
  document.querySelectorAll("details.meer[open]").forEach(function (menu) {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
