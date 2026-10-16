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
function sluit_meer_buiten(event) {
  var doel = event.target;
  document.querySelectorAll("details.meer[open]").forEach(function (menu) {
    if (!menu.contains(doel)) menu.open = false;
  });
}
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape") sluit_meer();
});
document.addEventListener("pointerdown", sluit_meer_buiten);
document.addEventListener("touchstart", sluit_meer_buiten, { passive: true });
document.addEventListener("click", sluit_meer_buiten);
function weekritme(code) {
  return code === "week" || code === "twee_weken" || code === "vier_weken";
}
function toon_ritme() {
  var select = document.getElementById("frequentie");
  var dag = document.getElementById("afschrijfdag-veld");
  var vanaf = document.getElementById("referentie-veld");
  if (!select || !dag || !vanaf) return;
  var week = weekritme(select.value);
  dag.hidden = week;
  vanaf.hidden = !week;
}
var frequentie = document.getElementById("frequentie");
if (frequentie) frequentie.addEventListener("change", toon_ritme);
toon_ritme();
