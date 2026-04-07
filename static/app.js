/**
 * NotSoCoolCard - Frontend JavaScript for card search and deck validation.
 *
 * Handles UI interactions, filtering, sorting, and deck checking.
 */

let ALL_CARDS = [];
let CARD_LOOKUP = new Map();
let SYMBOLOGY = {};
const PAGE_SIZE = 100;
let currentPage = 1;
let currentFilteredSorted = [];
let USD_SEK_RATE = null;

// DOM element references for easy access
const el = {
  searchTabBtn: document.getElementById("searchTabBtn"),
  deckCheckTabBtn: document.getElementById("deckCheckTabBtn"),
  searchTab: document.getElementById("searchTab"),
  deckCheckTab: document.getElementById("deckCheckTab"),
  name: document.getElementById("nameFilter"),
  include: document.getElementById("includeFilter"),
  price: document.getElementById("priceFilter"),
  tag: document.getElementById("tagFilter"),
  typeInclude: document.getElementById("typeIncludeFilter"),
  typeExclude: document.getElementById("typeExcludeFilter"),
  cmc: document.getElementById("cmcFilter"),
  cmcMode: document.getElementById("cmcModeFilter"),
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
  deckUrlInput: document.getElementById("deckUrlInput"),
  fetchDeckBtn: document.getElementById("fetchDeckBtn"),
  decklistInput: document.getElementById("decklistInput"),
  deckThresholdMode: document.getElementById("deckThresholdMode"),
  deckThresholdFilter: document.getElementById("deckThresholdFilter"),
  deckThresholdLabel: document.getElementById("deckThresholdLabel"),
  excludeLandsCheckbox: document.getElementById("excludeLandsCheckbox"),
  checkDeckBtn: document.getElementById("checkDeckBtn"),
  deckInfoBox: document.getElementById("deckInfoBox"),
  deckResults: document.getElementById("deckResults"),
};

// Utility functions
function asArray(v){ return Array.isArray(v) ? v : (v ? [v] : []); }
function normalizeText(v){ return String(v || "").toLowerCase().replace(/[^\w\s']/g," ").replace(/\s+/g," ").trim(); }
function parseCommaTerms(v){ return String(v || "").split(",").map(x => normalizeText(x)).filter(Boolean); }
function usdPrice(card){ const usd = card?.price?.usd; const n = Number(usd); return Number.isFinite(n) ? n : null; }
function sekPrice(card){ const usd = usdPrice(card); return usd !== null && USD_SEK_RATE !== null ? usd * USD_SEK_RATE : null; }
function formatSek(v){ return v === null ? "—" : new Intl.NumberFormat("sv-SE",{minimumFractionDigits:2,maximumFractionDigits:2}).format(v); }
function buildCardLookup(cards){ const m = new Map(); for(const c of cards){ const k = normalizeText(c.name); if(k && !m.has(k)) m.set(k,c);} return m; }

function getExactColorFilter(){ const order = ["W","U","B","R","G","COLORLESS"]; const selected = Array.from(document.querySelectorAll('input[name="exactColor"]:checked')).map(el=>el.value); if(!selected.length) return ""; if(selected.includes("COLORLESS") && selected.length===1) return "COLORLESS"; const selectedColors = order.filter(code=>code!="COLORLESS" && selected.includes(code)); return selectedColors.join(""); }
function getCommanderIdentity(){ const c=[]; if(el.commanderW.checked)c.push("W"); if(el.commanderU.checked)c.push("U"); if(el.commanderB.checked)c.push("B"); if(el.commanderR.checked)c.push("R"); if(el.commanderG.checked)c.push("G"); if(document.getElementById("commanderC")?.checked) c.push("C"); return c; }
function cardFitsCommanderIdentity(card, commanderColors){ if(!commanderColors.length) return true; const cc = Array.isArray(card.color_identity)&&card.color_identity.length ? card.color_identity : (card.color&&card.color!=="COLORLESS" ? card.color.split("") : []); return cc.every(x=>commanderColors.includes(x)); }
function manaPassesFilter(cmc){ const f = el.cmc.value==="" ? null : Number(el.cmc.value); if(f===null) return true; const c = Number(cmc ?? Infinity); if(el.cmcMode.value==="eq") return c===f; if(el.cmcMode.value==="gte") return c>=f; return c<=f; }
function typePassesFilter(type){ const txt = normalizeText(type); const include = parseCommaTerms(el.typeInclude.value); const exclude = parseCommaTerms(el.typeExclude.value); if(include.length && !include.some(t=>txt.includes(t))) return false; if(exclude.some(t=>txt.includes(t))) return false; return true; }

// Check if a card matches the current filter criteria
function cardMatches(card){
  const name = normalizeText(card.name), color = String(card.color || "COLORLESS"), tags = asArray(card.tags).join(" | ").toLowerCase();
  const includePct = Number(card.include_pct ?? Infinity), sek = sekPrice(card), commanderColors = getCommanderIdentity();
  const exactColor = getExactColorFilter();
  if(normalizeText(el.name.value) && !name.includes(normalizeText(el.name.value))) return false;
  if(exactColor && color !== exactColor) return false;
  if(normalizeText(el.tag.value) && !tags.includes(normalizeText(el.tag.value))) return false;
  if(el.include.value !== "" && !(includePct <= Number(el.include.value))) return false;
  if(el.price.value !== "" && !(sek !== null && sek <= Number(el.price.value))) return false;
  if(!manaPassesFilter(card.cmc)) return false;
  if(!typePassesFilter(card.card_type)) return false;
  if(el.limitCommander.checked && !cardFitsCommanderIdentity(card, commanderColors)) return false;
  return true;
}

// Sort cards based on selected sorting criteria
function sortCards(cards){
  const mode = el.sort.value;
  return [...cards].sort((a,b)=>{
    if(mode==="include_desc") return (b.include_pct??-Infinity)-(a.include_pct??-Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="include_asc") return (a.include_pct??Infinity)-(b.include_pct??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="price_asc") return (sekPrice(a)??Infinity)-(sekPrice(b)??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="price_desc") return (sekPrice(b)??-Infinity)-(sekPrice(a)??-Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="cmc_asc") return (a.cmc??Infinity)-(b.cmc??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="edhrec_rank_asc") return (a.edhrec_rank??Infinity)-(b.edhrec_rank??Infinity)||String(a.name).localeCompare(String(b.name));
    return String(a.name).localeCompare(String(b.name));
  });
}

function updatePaginationUI(total){
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const start = total===0 ? 0 : (currentPage-1)*PAGE_SIZE+1;
  const end = Math.min(currentPage*PAGE_SIZE,total);
  const text = total===0 ? "Page 1 of 1 • 0 results" : `Page ${currentPage} of ${totalPages} • showing ${start}-${end} of ${total}`;
  el.pageSummary.textContent = text; el.pageSummaryBottom.textContent = text;
  const prevDisabled = currentPage<=1, nextDisabled = currentPage>=totalPages || total===0;
  el.prevPageBtn.disabled = prevDisabled; el.prevPageBtnBottom.disabled = prevDisabled;
  el.nextPageBtn.disabled = nextDisabled; el.nextPageBtnBottom.disabled = nextDisabled;
}

function renderManaCost(manaCost){
  if(!manaCost) return "Mana cost: —";
  const wrapper = document.createElement("span");
  wrapper.className = "mana-pips";
  const tokens = String(manaCost).match(/\{[^}]+\}/g) || [];
  if(!tokens.length){ wrapper.textContent = manaCost; return wrapper.outerHTML; }
  for(const token of tokens){
    const img = document.createElement("img");
    img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
    wrapper.appendChild(img);
  }
  return wrapper.outerHTML;
}

function renderColorIdentityPips(card){
  const tokens = [];
  if(Array.isArray(card.color_identity) && card.color_identity.length){
    for(const color of card.color_identity){
      if(color) tokens.push(`{${String(color).toUpperCase()}}`);
    }
  } else if(String(card.color || "").toUpperCase() === "COLORLESS"){
    tokens.push("{C}");
  }
  if(!tokens.length) return "Identity: —";
  const wrapper = document.createElement("span");
  wrapper.className = "mana-pips";
  for(const token of tokens){
    const img = document.createElement("img");
    img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
    wrapper.appendChild(img);
  }
  return wrapper.outerHTML;
}

function renderCards(cards){
  el.results.innerHTML = "";
  if(!cards.length){ const d=document.createElement("div"); d.className="empty-state"; d.textContent="No cards match your filters."; el.results.appendChild(d); updatePaginationUI(0); return; }
  const totalPages = Math.max(1, Math.ceil(cards.length / PAGE_SIZE));
  if(currentPage>totalPages) currentPage = totalPages;
  const pageCards = cards.slice((currentPage-1)*PAGE_SIZE, currentPage*PAGE_SIZE);
  const commanderColors=getCommanderIdentity(), commanderLabel=commanderColors.length?commanderColors.join(""):"Any";
  for(const card of pageCards){
    const node = el.template.content.cloneNode(true);
    node.querySelector(".card-name").textContent = card.name || "Unknown";
    node.querySelector(".meta-row").textContent = `${card.card_type||"—"}${card.edhrec_rank ? " • EDHREC rank "+card.edhrec_rank : ""}`;
    node.querySelector(".mana-row").innerHTML = `Mana cost: ${renderManaCost(card.mana_cost)}`;
    node.querySelector(".tags-row").textContent = `Tags: ${asArray(card.tags).length ? asArray(card.tags).join(", ") : "—"}`;
    node.querySelector(".color-pill").textContent = `Color: ${card.color||"COLORLESS"}`;
    node.querySelector(".include-pill").textContent = `Include %: ${card.include_pct ?? "—"}`;
    node.querySelector(".cmc-pill").textContent = `MV: ${card.cmc ?? "—"}`;
    node.querySelector(".commander-pill").innerHTML = renderColorIdentityPips(card);
    node.querySelector(".price-pill").textContent = `SEK: ${formatSek(sekPrice(card))}`;
    node.querySelector(".edhrec-link").href = card.edhrec_link || "#";
    node.querySelector(".scryfall-link").href = card.scryfall_link || "#";
    node.querySelector(".image-link").href = card.image_url || "#";
    const img = node.querySelector(".card-image");
    img.alt = card.name || "Card image"; img.src = card.image_url || "";
    if(!el.imageToggle.checked || !card.image_url) node.querySelector(".image-wrap").style.display = "none";
    el.results.appendChild(node);
  }
  updatePaginationUI(cards.length);
}

function applyFilters(reset=false){
  if(reset) currentPage = 1;
  currentFilteredSorted = sortCards(ALL_CARDS.filter(cardMatches));
  renderCards(currentFilteredSorted);
  const commanderColors=getCommanderIdentity();
  const commanderText=el.limitCommander.checked ? ` • commander identity ${commanderColors.length ? commanderColors.join("") : "none selected"}` : "";
  el.summary.textContent = `${currentFilteredSorted.length} / ${ALL_CARDS.length} cards shown${commanderText}`;
}

function nextPage(){ const totalPages=Math.max(1, Math.ceil(currentFilteredSorted.length/PAGE_SIZE)); if(currentPage<totalPages){ currentPage++; renderCards(currentFilteredSorted); window.scrollTo({top:0,behavior:"smooth"});} }
function prevPage(){ if(currentPage>1){ currentPage--; renderCards(currentFilteredSorted); window.scrollTo({top:0,behavior:"smooth"});} }

function parseDecklist(text){
  const entries = [];
  for(const raw of String(text||"").split(/\r?\n/)){
    const line = raw.trim(); if(!line || line.startsWith("#") || line.startsWith("//")) continue;
    const m = line.match(/^(\d+)\s*x?\s+(.+)$/i); if(!m) continue;
    entries.push({quantity:Number(m[1]), name:m[2].trim()});
  }
  return entries;
}

function normalizeCardType(card){
  const raw = card.card_type || card.type || card.types || "";
  if(Array.isArray(raw)) return raw.join(" ");
  return String(raw || "");
}

function cardIsLand(card){
  return normalizeText(normalizeCardType(card)).includes("land");
}

function cardIsBasicLand(card){
  const raw = card.supertypes || card.supertype || card.super_types || "";
  if(Array.isArray(raw)) return raw.some(v=>normalizeText(v).includes("basic"));
  return normalizeText(String(raw)).includes("basic");
}

function parseIncludePct(card){
  const raw = card.include_pct;
  const n = Number(raw);
  return Number.isFinite(n) ? n : Infinity;
}

function renderDeckCheckResults(result){
  const c = document.createElement("div"); c.className="deck-check-report";
  const s = document.createElement("div"); s.className="deck-summary";
  s.innerHTML = `<div>Lands: <strong>${result.landsCount}</strong></div><div>Cards above threshold: <strong>${result.aboveThreshold.length}</strong></div><div>Cards under threshold: <strong>${result.underThreshold.length}</strong></div>`;
  c.appendChild(s);
  if(result.blocked){ const w=document.createElement("div"); w.className="warning-box"; w.textContent=result.message; c.appendChild(w); return c; }
  if(!result.aboveThreshold.length){ const ok=document.createElement("div"); ok.className="success-box"; ok.textContent=`Deck passed. All checked cards are at or below the threshold.`; c.appendChild(ok); }
  const sectionGroup = document.createElement("div"); sectionGroup.className = "threshold-columns";
  if(result.aboveThreshold.length){ const sec=document.createElement("section"); sec.innerHTML="<h3>Above threshold</h3>"; const list=document.createElement("ul"); list.className="report-list"; for(const o of result.aboveThreshold){ const li=document.createElement("li"); li.textContent = o.assumed ? `${o.quantity} ${o.name}` : `${o.quantity} ${o.name} — ${result.thresholdMode === "price" ? formatSek(o.price) : `${o.include_pct}%`}`; list.appendChild(li);} sec.appendChild(list); sectionGroup.appendChild(sec); }
  if(result.underThreshold.length){ const sec=document.createElement("section"); sec.innerHTML="<h3>Under threshold</h3>"; const list=document.createElement("ul"); list.className="report-list"; for(const o of result.underThreshold){ const li=document.createElement("li"); li.textContent = `${o.quantity} ${o.name} — ${result.thresholdMode === "price" ? formatSek(o.price) : `${o.include_pct}%`}`; list.appendChild(li);} sec.appendChild(list); sectionGroup.appendChild(sec); }
  if(sectionGroup.children.length) c.appendChild(sectionGroup);
  if(result.excludedLands.length){ const sec=document.createElement("section"); sec.innerHTML="<h3>Excluded lands</h3>"; const list=document.createElement("ul"); list.className="report-list"; for(const l of result.excludedLands){ const li=document.createElement("li"); li.textContent = `${l.quantity} ${l.name}`; list.appendChild(li);} sec.appendChild(list); c.appendChild(sec); }
  if(result.basicLands.length){ const sec=document.createElement("section"); sec.innerHTML="<h3>Basic Lands</h3>"; const list=document.createElement("ul"); list.className="report-list"; for(const l of result.basicLands){ const li=document.createElement("li"); li.textContent = `${l.quantity} ${l.name}`; list.appendChild(li);} sec.appendChild(list); c.appendChild(sec); }
  return c;
}

function checkDeck(){
  const entries = parseDecklist(el.decklistInput.value), totalCards = entries.reduce((s,e)=>s+e.quantity,0); el.deckResults.innerHTML="";
  if(!entries.length){ el.deckInfoBox.textContent="No valid decklist lines found."; return; }
  el.deckInfoBox.textContent=`Deck contains ${totalCards} cards.`;
  const threshold = Number(el.deckThresholdFilter.value||2);
  const thresholdMode = el.deckThresholdMode.value || "include";
  const excludeLands = el.excludeLandsCheckbox.checked;
  if(totalCards>100){ el.deckResults.appendChild(renderDeckCheckResults({blocked:true,message:`Deck has ${totalCards} cards. The checker will not run for decklists above 100 cards.`,totalCards,landsCount:0,aboveThreshold:[],underThreshold:[],excludedLands:[],basicLands:[],thresholdMode})); return; }
  const aboveThreshold=[], underThreshold=[], excludedLands=[], basicLands=[]; let landsCount=0;
  for(const entry of entries){
    const card = CARD_LOOKUP.get(normalizeText(entry.name));
    if(!card){ aboveThreshold.push({quantity:entry.quantity,name:entry.name,assumed:true}); continue; }
    const isLand = cardIsLand(card);
    const isBasicLand = cardIsBasicLand(card);
    if(isLand){
      landsCount += entry.quantity;
      if(isBasicLand){
        basicLands.push({quantity:entry.quantity,name:card.name});
      }
      if(excludeLands){
        excludedLands.push({quantity:entry.quantity,name:card.name});
        continue;
      }
    }
    const includePct = parseIncludePct(card);
    const cardPrice = sekPrice(card);
    const entryData = {quantity: entry.quantity, name: card.name, include_pct: includePct, price: cardPrice};
    if(thresholdMode === "price"){
      if(cardPrice === null || cardPrice > threshold) aboveThreshold.push(entryData);
      else underThreshold.push(entryData);
    } else {
      if(includePct <= threshold) underThreshold.push(entryData);
      else aboveThreshold.push(entryData);
    }
  }
  el.deckResults.appendChild(renderDeckCheckResults({blocked:false,totalCards,landsCount,aboveThreshold,underThreshold,excludedLands,basicLands,thresholdMode}));
}

async function fetchDecklistFromUrl(){
  const url = el.deckUrlInput.value.trim(); if(!url){ el.deckInfoBox.textContent="Paste a deck URL first."; return; }
  el.deckInfoBox.textContent="Fetching decklist…";
  try{
    const response = await fetch("/api/deck-resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
    const text = await response.text();
    let data;
    try{
      data = JSON.parse(text);
    }catch(err){
      console.error("fetchDecklistFromUrl: invalid JSON response", text);
      throw new Error("Invalid server response while fetching decklist.");
    }
    if(!response.ok || !data.ok){
      console.error("fetchDecklistFromUrl error", response.status, data);
      throw new Error(data.error || `Server returned ${response.status}`);
    }
    el.decklistInput.value = data.decklist;
    const total = parseDecklist(data.decklist).reduce((s,e)=>s+e.quantity,0);
    el.deckInfoBox.textContent = `Fetched ${total} cards from ${data.source}.`;
  }catch(error){
    console.error("fetchDecklistFromUrl catch", error);
    el.deckInfoBox.textContent = error.message || "Could not fetch decklist.";
  }
}

function updateDeckThresholdLabel(){
  const labelText = el.deckThresholdMode.value === "price" ? "Max SEK price" : "Max Include %";
  const labelSpan = el.deckThresholdLabel.querySelector("span");
  if(labelSpan) labelSpan.textContent = labelText;
}

function activateTab(which){
  const isSearch = which==="search";
  el.searchTabBtn.classList.toggle("active",isSearch);
  el.deckCheckTabBtn.classList.toggle("active",!isSearch);
  el.searchTab.classList.toggle("active",isSearch);
  el.deckCheckTab.classList.toggle("active",!isSearch);
}

async function init(){
  const [cardsResp, symResp] = await Promise.all([fetch("/api/cards"), fetch("/api/symbology")]);
  const cardsData = await cardsResp.json(); const symData = await symResp.json();
  ALL_CARDS = Array.isArray(cardsData.cards) ? cardsData.cards : [];
  CARD_LOOKUP = buildCardLookup(ALL_CARDS);
  USD_SEK_RATE = cardsData?.meta?.usd_sek_rate != null ? Number(cardsData.meta.usd_sek_rate) : null;
  SYMBOLOGY = symData?.symbols || {};
  document.querySelectorAll('.pip-symbol[data-symbol]').forEach(pip=>{
    const symbolToken = pip.getAttribute('data-symbol');
    const svgUrl = SYMBOLOGY[symbolToken];
    if(svgUrl) pip.style.backgroundImage = `url('${svgUrl}')`;
  });
  applyFilters(true);
}

for(const control of [el.name,el.include,el.price,el.tag,el.typeInclude,el.typeExclude,el.cmc,el.cmcMode,el.sort,el.imageToggle,el.limitCommander,el.commanderW,el.commanderU,el.commanderB,el.commanderR,el.commanderG,document.getElementById("commanderC")]){
  if(!control) continue;
  control.addEventListener("input",()=>applyFilters(true));
  control.addEventListener("change",()=>applyFilters(true));
}
document.querySelectorAll('input[name="exactColor"]').forEach(radio=>{
  radio.addEventListener("change",()=>applyFilters(true));
});
el.deckThresholdMode.addEventListener("change", updateDeckThresholdLabel);
updateDeckThresholdLabel();
el.nextPageBtn.addEventListener("click",nextPage); el.nextPageBtnBottom.addEventListener("click",nextPage);
el.prevPageBtn.addEventListener("click",prevPage); el.prevPageBtnBottom.addEventListener("click",prevPage);
el.searchTabBtn.addEventListener("click",()=>activateTab("search")); el.deckCheckTabBtn.addEventListener("click",()=>activateTab("deck"));
el.fetchDeckBtn.addEventListener("click",fetchDecklistFromUrl); el.checkDeckBtn.addEventListener("click",checkDeck);
init();
