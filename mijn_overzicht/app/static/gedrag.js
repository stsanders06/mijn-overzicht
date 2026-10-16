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
var WEEK_RITME = { week: true, twee_weken: true, vier_weken: true };
function toon_ritme() {
  var frequentie = document.getElementById("frequentie");
  var dag = document.getElementById("afschrijfdag-veld");
  var vanaf = document.getElementById("referentie-veld");
  if (!frequentie || !dag || !vanaf) return;
  var week = Object.prototype.hasOwnProperty.call(WEEK_RITME, frequentie.value);
  dag.hidden = week;
  vanaf.hidden = !week;
}
var frequentie_veld = document.getElementById("frequentie");
if (frequentie_veld) {
  frequentie_veld.addEventListener("change", toon_ritme);
  toon_ritme();
}
function toon_soort() {
  var soort = document.getElementById("soort");
  var toeslag = document.getElementById("toeslag-veld");
  var hint = document.getElementById("toeslag-hint");
  var uren = document.getElementById("uren-veld");
  if (!soort || !toeslag || !hint || !uren) return;
  var is_toeslag = soort.value === "toeslag";
  toeslag.hidden = !is_toeslag;
  hint.hidden = !is_toeslag;
  uren.hidden = is_toeslag;
}
var soort_veld = document.getElementById("soort");
if (soort_veld) {
  soort_veld.addEventListener("change", toon_soort);
  toon_soort();
}
