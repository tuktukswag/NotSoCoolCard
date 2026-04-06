let ALL_CARDS = [];
const PAGE_SIZE = 100;
let currentPage = 1;
let currentFilteredSorted = [];

const el = {
  name: document.getElementById("nameFilter"),
  color: document.getElementById("colorFilter"),
  include: document.getElementById("includeFilter"),
  price: document.getElementById("priceFilter"),
  tag: document.getElementById("tagFilter"),
  type: document.getElementById("typeFilter"),
  cmc: document.getElementById("cmcFilter"),
  sort: document.getElementById("sortFilter"),
  imageToggle: document.getElementById("imageToggle"),
  limitCommander: document.getElementById("limitToCommanderIdentity"),
  commanderW: document.getElementById("commanderW"),
  commanderU: document.getElementById("commanderU"),
  commanderB: document.getElementById("commanderB"),
  commanderR: document.getElementById("commanderR"),
  commanderG: document.getElementById("commanderG"),
  results: document.getElementById("results"),
  summary: document.getElementById("summary"),
  template: document.getElementById("cardTemplate"),
  prevPageBtn: document.getElementById("prevPageBtn"),
  nextPageBtn: document.getElementById("nextPageBtn"),
  prevPageBtnBottom: document.getElementById("prevPageBtnBottom"),
  nextPageBtnBottom: document.getElementById("nextPageBtnBottom"),
  pageSummary: document.getElementById("pageSummary"),
  pageSummaryBottom: document.getElementById("pageSummaryBottom"),
};

function asArray(value) { if (Array.isArray(value)) return value; if (!value) return []; return [value]; }
function normalizeText(value) { return String(value || "").toLowerCase().trim(); }
function numericPrice(card) { const usd = card?.price?.usd; if (usd === null || usd === undefined || usd === "") return null; const value = Number(usd); return Number.isFinite(value) ? value : null; }

function getCommanderIdentity() {
  const colors = [];
  if (el.commanderW.checked) colors.push("W");
  if (el.commanderU.checked) colors.push("U");
  if (el.commanderB.checked) colors.push("B");
  if (el.commanderR.checked) colors.push("R");
  if (el.commanderG.checked) colors.push("G");
  return colors;
}

function cardFitsCommanderIdentity(card, commanderColors) {
  if (!commanderColors.length) return true;
  const cardColors = Array.isArray(card.color_identity) && card.color_identity.length ? card.color_identity : (card.color && card.color !== "COLORLESS" ? card.color.split("") : []);
  return cardColors.every(color => commanderColors.includes(color));
}

function cardMatches(card) {
  const nameFilter = normalizeText(el.name.value);
  const colorFilter = el.color.value.trim();
  const tagFilter = normalizeText(el.tag.value);
  const typeFilter = normalizeText(el.type.value);
  const includeFilter = el.include.value === "" ? null : Number(el.include.value);
  const priceFilter = el.price.value === "" ? null : Number(el.price.value);
  const cmcFilter = el.cmc.value === "" ? null : Number(el.cmc.value);
  const commanderColors = getCommanderIdentity();

  const name = normalizeText(card.name);
  const color = String(card.color || "COLORLESS");
  const tags = asArray(card.tags).join(" | ").toLowerCase();
  const type = normalizeText(card.card_type);
  const includePct = Number(card.include_pct ?? Infinity);
  const cmc = Number(card.cmc ?? Infinity);
  const usdPrice = numericPrice(card);

  if (nameFilter && !name.includes(nameFilter)) return false;
  if (colorFilter && color !== colorFilter) return false;
  if (tagFilter && !tags.includes(tagFilter)) return false;
  if (typeFilter && !type.includes(typeFilter)) return false;
  if (includeFilter !== null && !(includePct <= includeFilter)) return false;
  if (cmcFilter !== null && !(cmc <= cmcFilter)) return false;
  if (priceFilter !== null && !(usdPrice !== null && usdPrice <= priceFilter)) return false;
  if (el.limitCommander.checked && !cardFitsCommanderIdentity(card, commanderColors)) return false;
  return true;
}

function sortCards(cards) {
  const mode = el.sort.value;
  const sorted = [...cards];
  sorted.sort((a, b) => {
    if (mode === "include_desc") return (b.include_pct ?? -Infinity) - (a.include_pct ?? -Infinity) || String(a.name).localeCompare(String(b.name));
    if (mode === "include_asc") return (a.include_pct ?? Infinity) - (b.include_pct ?? Infinity) || String(a.name).localeCompare(String(b.name));
    if (mode === "price_asc") return (numericPrice(a) ?? Infinity) - (numericPrice(b) ?? Infinity) || String(a.name).localeCompare(String(b.name));
    if (mode === "price_desc") return (numericPrice(b) ?? -Infinity) - (numericPrice(a) ?? -Infinity) || String(a.name).localeCompare(String(b.name));
    if (mode === "name_asc") return String(a.name).localeCompare(String(b.name));
    if (mode === "cmc_asc") return (a.cmc ?? Infinity) - (b.cmc ?? Infinity) || String(a.name).localeCompare(String(b.name));
    if (mode === "edhrec_rank_asc") return (a.edhrec_rank ?? Infinity) - (b.edhrec_rank ?? Infinity) || String(a.name).localeCompare(String(b.name));
    return 0;
  });
  return sorted;
}

function updatePaginationUI(totalCards) {
  const totalPages = Math.max(1, Math.ceil(totalCards / PAGE_SIZE));
  const startIndex = totalCards === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const endIndex = Math.min(currentPage * PAGE_SIZE, totalCards);
  const text = totalCards === 0 ? "Page 1 of 1 • 0 results" : `Page ${currentPage} of ${totalPages} • showing ${startIndex}-${endIndex} of ${totalCards}`;
  el.pageSummary.textContent = text;
  el.pageSummaryBottom.textContent = text;
  const disablePrev = currentPage <= 1;
  const disableNext = currentPage >= totalPages || totalCards === 0;
  el.prevPageBtn.disabled = disablePrev;
  el.prevPageBtnBottom.disabled = disablePrev;
  el.nextPageBtn.disabled = disableNext;
  el.nextPageBtnBottom.disabled = disableNext;
}

function renderCards(cards) {
  el.results.innerHTML = "";
  if (!cards.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No cards match your filters.";
    el.results.appendChild(empty);
    updatePaginationUI(0);
    return;
  }

  const totalPages = Math.max(1, Math.ceil(cards.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const start = (currentPage - 1) * PAGE_SIZE;
  const pageCards = cards.slice(start, start + PAGE_SIZE);

  const showImages = el.imageToggle.checked;
  const commanderColors = getCommanderIdentity();
  const commanderLabel = commanderColors.length ? commanderColors.join("") : "Any";

  for (const card of pageCards) {
    const node = el.template.content.cloneNode(true);
    const imageWrap = node.querySelector(".image-wrap");
    const image = node.querySelector(".card-image");
    const name = node.querySelector(".card-name");
    const meta = node.querySelector(".meta-row");
    const mana = node.querySelector(".mana-row");
    const priceRow = node.querySelector(".price-row");
    const tags = node.querySelector(".tags-row");
    const colorPill = node.querySelector(".color-pill");
    const includePill = node.querySelector(".include-pill");
    const cmcPill = node.querySelector(".cmc-pill");
    const commanderPill = node.querySelector(".commander-pill");
    const pricePill = node.querySelector(".price-pill");
    const edhrecLink = node.querySelector(".edhrec-link");
    const scryfallLink = node.querySelector(".scryfall-link");
    const imageLink = node.querySelector(".image-link");

    const usd = card?.price?.usd || "—";
    const usdFoil = card?.price?.usd_foil || "—";
    const eur = card?.price?.eur || "—";

    name.textContent = card.name || "Unknown";
    meta.textContent = `${card.card_type || "—"}${card.edhrec_rank ? " • EDHREC rank " + card.edhrec_rank : ""}`;
    mana.textContent = `Mana cost: ${card.mana_cost || "—"} • Mana value: ${card.cmc ?? "—"}`;
    priceRow.textContent = `Price: USD ${usd} • Foil ${usdFoil} • EUR ${eur}`;
    tags.textContent = `Tags: ${asArray(card.tags).length ? asArray(card.tags).join(", ") : "—"}`;
    colorPill.textContent = `Color: ${card.color || "COLORLESS"}`;
    includePill.textContent = `Include %: ${card.include_pct ?? "—"}`;
    cmcPill.textContent = `MV: ${card.cmc ?? "—"}`;
    commanderPill.textContent = `Commander: ${commanderLabel}`;
    pricePill.textContent = `USD: ${usd}`;
    edhrecLink.href = card.edhrec_link || "#";
    scryfallLink.href = card.scryfall_link || "#";
    imageLink.href = card.image_url || "#";
    image.alt = card.name || "Card image";
    image.src = card.image_url || "";
    if (!showImages || !card.image_url) imageWrap.style.display = "none";
    el.results.appendChild(node);
  }

  updatePaginationUI(cards.length);
}

function applyFilters(resetPage = false) {
  if (resetPage) currentPage = 1;
  currentFilteredSorted = sortCards(ALL_CARDS.filter(cardMatches));
  renderCards(currentFilteredSorted);
  const commanderColors = getCommanderIdentity();
  const commanderText = el.limitCommander.checked ? ` • commander identity ${commanderColors.length ? commanderColors.join("") : "none selected"}` : "";
  el.summary.textContent = `${currentFilteredSorted.length} / ${ALL_CARDS.length} cards shown${commanderText}`;
}

function nextPage() {
  const totalPages = Math.max(1, Math.ceil(currentFilteredSorted.length / PAGE_SIZE));
  if (currentPage < totalPages) {
    currentPage += 1;
    renderCards(currentFilteredSorted);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function prevPage() {
  if (currentPage > 1) {
    currentPage -= 1;
    renderCards(currentFilteredSorted);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

async function init() {
  const response = await fetch("/api/cards");
  const data = await response.json();
  ALL_CARDS = Array.isArray(data.cards) ? data.cards : [];
  applyFilters(true);
}

for (const control of [el.name, el.color, el.include, el.price, el.tag, el.type, el.cmc, el.sort, el.imageToggle, el.limitCommander, el.commanderW, el.commanderU, el.commanderB, el.commanderR, el.commanderG]) {
  control.addEventListener("input", () => applyFilters(true));
  control.addEventListener("change", () => applyFilters(true));
}
el.nextPageBtn.addEventListener("click", nextPage);
el.nextPageBtnBottom.addEventListener("click", nextPage);
el.prevPageBtn.addEventListener("click", prevPage);
el.prevPageBtnBottom.addEventListener("click", prevPage);
init();
