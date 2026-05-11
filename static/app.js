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
  set: document.getElementById("setFilter"),
  include: document.getElementById("includeFilter"),
  price: document.getElementById("priceFilter"),
  tag: document.getElementById("tagFilter"),
  text: document.getElementById("textFilter"),
  typeInclude: document.getElementById("typeIncludeFilter"),
  typeExclude: document.getElementById("typeExcludeFilter"),
  showTagsToggle: document.getElementById("showTagsToggle"),
  searchFiltersBtn: document.getElementById("searchFiltersBtn"),
  resetFiltersBtn: document.getElementById("resetFiltersBtn"),
  cmcMin: document.getElementById("cmcMinFilter"),
  cmcMax: document.getElementById("cmcMaxFilter"),
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
function normalizeTagText(v){ return String(v || "").toLowerCase().replace(/[^\w\s-]/g," ").replace(/\s+/g," ").trim(); }
function parseFilterClauses(v, normalizeTerm = normalizeText){
  return String(v || "")
    .split(",")
    .map(group => group.split("|").map(term => normalizeTerm(term)).filter(Boolean))
    .filter(group => group.length > 0);
}
function parseCommaTerms(v){ return parseFilterClauses(v).flat(); }
function parseTextFilterTerms(v){ return parseFilterClauses(v); }
function normalizeTagTerm(v){ return normalizeText(String(v || "").replace(/^o?tag\s*:\s*/i, "")); }
function escapeRegExp(v){ return String(v || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function parseTagFilterTerms(v){
  return String(v || "")
    .split(",")
    .map(group => group.split("|")
      .map(term => {
        const raw = String(term || "").trim().replace(/^o?tag\s*:\s*/i, "");
        const exact = /^".*"$/.test(raw);
        const normalized = normalizeTagText(exact ? raw.slice(1, -1) : raw);
        return normalized ? { term: normalized, exact } : null;
      })
      .filter(Boolean)
    )
    .filter(group => group.length > 0);
}
function textMatchesClauses(text, clauses){
  if(!clauses.length) return true;
  return clauses.every(group => group.some(term => text.includes(term)));
}
function tagMatchesTerm(tagText, tagTerm){
  if(!tagTerm?.term) return false;
  if(!tagTerm.exact) return tagText.includes(tagTerm.term);
  const pattern = new RegExp(`(^|[\\s-])${escapeRegExp(tagTerm.term)}($|[\\s-])`);
  return pattern.test(tagText);
}
function tagMatchesClauses(tagText, clauses){
  if(!clauses.length) return true;
  return clauses.every(group => group.some(term => tagMatchesTerm(tagText, term)));
}
function slugifyCardName(v){ return String(v || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[’'`]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""); }
function buildEdhrecLink(card){
  if(card?.edhrec_link) return card.edhrec_link;
  if(card?.edhrec_url) return card.edhrec_url;
  const slug = slugifyCardName(card?.name);
  return slug ? `https://edhrec.com/cards/${slug}` : "#";
}
function buildScryfallLink(card){
  if(card?.scryfall_link) return card.scryfall_link;
  const setCode = String(card?.set || card?.set_code || "").toLowerCase().trim();
  const collector = String(card?.collector_number || "").toLowerCase().trim();
  if(setCode && collector) return `https://scryfall.com/card/${encodeURIComponent(setCode)}/${encodeURIComponent(collector)}`;
  const name = String(card?.name || "").trim();
  return name ? `https://scryfall.com/search?q=${encodeURIComponent(`!\"${name}\"`)}` : "#";
}
function usdPrice(card){ const usd = card?.price?.usd; const n = Number(usd); return Number.isFinite(n) ? n : null; }
function sekPrice(card){ const usd = usdPrice(card); return usd !== null && USD_SEK_RATE !== null ? usd * USD_SEK_RATE : null; }
function formatSek(v){ return v === null ? "—" : new Intl.NumberFormat("sv-SE",{minimumFractionDigits:2,maximumFractionDigits:2}).format(v); }
function buildCardLookup(cards){ const m = new Map(); for(const c of cards){ const k = normalizeText(c.name); if(k && !m.has(k)) m.set(k,c);} return m; }
function getCardSetCode(card){ return normalizeText(card?.set || card?.set_code || card?.set_shortname || ""); }

function getExactColorFilter(){ const order = ["W","U","B","R","G","COLORLESS"]; const selected = Array.from(document.querySelectorAll('input[name="exactColor"]:checked')).map(el=>el.value); if(!selected.length) return ""; if(selected.includes("COLORLESS") && selected.length===1) return "COLORLESS"; const selectedColors = order.filter(code=>code!="COLORLESS" && selected.includes(code)); return selectedColors.join(""); }
function getCommanderIdentity(){ const c=[]; if(el.commanderW.checked)c.push("W"); if(el.commanderU.checked)c.push("U"); if(el.commanderB.checked)c.push("B"); if(el.commanderR.checked)c.push("R"); if(el.commanderG.checked)c.push("G"); if(document.getElementById("commanderC")?.checked) c.push("C"); return c; }
function cardFitsCommanderIdentity(card, commanderColors){ if(!commanderColors.length) return true; const cc = Array.isArray(card.color_identity)&&card.color_identity.length ? card.color_identity : (card.color&&card.color!=="COLORLESS" ? card.color.split("") : []); return cc.every(x=>commanderColors.includes(x)); }
function manaPassesFilter(cmc){ const min = el.cmcMin.value==="" ? null : Number(el.cmcMin.value); const max = el.cmcMax.value==="" ? null : Number(el.cmcMax.value); if(min===null && max===null) return true; const c = Number(cmc ?? Infinity); if(min!==null && c<min) return false; if(max!==null && c>max) return false; return true; }
function typePassesFilter(type){
  const txt = normalizeText(type);
  const include = parseFilterClauses(el.typeInclude.value);
  const exclude = parseFilterClauses(el.typeExclude.value);
  if(!textMatchesClauses(txt, include)) return false;
  if(exclude.some(group => group.some(term => txt.includes(term)))) return false;
  return true;
}

function setPassesFilter(card){
  const clauses = parseFilterClauses(el.set?.value);
  if(!clauses.length) return true;
  const setCode = getCardSetCode(card);
  return clauses.every(group => group.some(term => setCode.includes(term)));
}

function getVisibleTags(card){
  const allTags = asArray(card.tags);
  if(!allTags.length) return [];
  if(el.showTagsToggle?.checked) return allTags;
  const tagTerms = parseTagFilterTerms(el.tag?.value);
  if(!tagTerms.length) return [];
  return allTags.filter(tag => {
    const norm = normalizeTagText(tag);
    return tagTerms.some(group => group.some(term => tagMatchesTerm(norm, term)));
  });
}

// Check if a card matches the current filter criteria
function cardMatches(card){
  const name = normalizeText(card.name), color = String(card.color || "COLORLESS"), tags = asArray(card.tags).map(normalizeTagText).join(" | ");
  const tagTerms = parseTagFilterTerms(el.tag?.value);
  const textTerms = parseTextFilterTerms(el.text?.value);
  const includePct = Number(card.include_pct ?? Infinity), sek = sekPrice(card), commanderColors = getCommanderIdentity();
  const exactColor = getExactColorFilter();
  if(normalizeText(el.name.value) && !name.includes(normalizeText(el.name.value))) return false;
  if(!setPassesFilter(card)) return false;
  if(exactColor && color !== exactColor) return false;
  if(!tagMatchesClauses(tags, tagTerms)) return false;
  if(textTerms.length){
    const oracleText = String(card._oracleTextNorm || "");
    if(!textMatchesClauses(oracleText, textTerms)) return false;
  }
  if(el.include.value !== "" && !(includePct <= Number(el.include.value))) return false;
  if(el.price.value !== "" && !(sek !== null && sek <= Number(el.price.value))) return false;
  if(!manaPassesFilter(card.cmc)) return false;
  if(!typePassesFilter(card.card_type)) return false;
  if(commanderColors.length && !cardFitsCommanderIdentity(card, commanderColors)) return false;
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
  if(!manaCost) return "—";
  const wrapper = document.createElement("span");
  wrapper.className = "mana-pips";
  // Handle split cards with //
  if(manaCost.includes(" // ")){
    const parts = manaCost.split(" // ");
    for(let i = 0; i < parts.length; i++){
      const tokens = String(parts[i]).match(/\{[^}]+\}/g) || [];
      for(const token of tokens){
        const img = document.createElement("img");
        img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
        wrapper.appendChild(img);
      }
      if(i < parts.length - 1){
        const slash = document.createElement("span");
        slash.textContent = " // ";
        wrapper.appendChild(slash);
      }
    }
  } else {
    const tokens = String(manaCost).match(/\{[^}]+\}/g) || [];
    if(!tokens.length){ wrapper.textContent = manaCost; return wrapper.outerHTML; }
    for(const token of tokens){
      const img = document.createElement("img");
      img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
      wrapper.appendChild(img);
    }
  }
  return wrapper.outerHTML;
}

function renderColorPips(card, manaCostOverride=null){
  const WUBRG = ["W","U","B","R","G"];
  const pill = document.createElement("span");
  pill.className = "pill-label-pips";
  const label = document.createElement("span");
  label.className = "pip-label"; label.textContent = "Color:";
  pill.appendChild(label);
  // Extract only colored symbols from mana cost (skip generic, X, snow, etc.)
  const colorSet = new Set();
  const sourceManaCost = manaCostOverride !== null && manaCostOverride !== undefined ? manaCostOverride : card.mana_cost;
  const manaCost = String(sourceManaCost || "").replace(/ \/\/ .+/, ""); // front face only
  const tokens = manaCost.match(/\{[^}]+\}/g) || [];
  const ordered = [];
  const seen = new Set();
  for(const tok of tokens){
    const inner = tok.slice(1,-1).toUpperCase();
    // hybrid pips like {W/U} — count both colours
    const parts = inner.split("/");
    for(const p of parts){
      if(WUBRG.includes(p)){
        colorSet.add(p);
        if(!seen.has(p)){
          seen.add(p);
          ordered.push(p);
        }
      }
    }
  }
  // Add any remaining colors in WUBRG order (normally none, but keeps behavior robust).
  for(const c of WUBRG){
    if(colorSet.has(c) && !seen.has(c)) ordered.push(c);
  }
  if(!ordered.length){
    // no mana cost at all (lands etc.) — show dash; purely generic cost — show {C}
    if(!tokens.length){
      pill.appendChild(document.createTextNode(" —"));
    } else {
      const wrapper = document.createElement("span");
      wrapper.className = "mana-pips";
      const img = document.createElement("img");
      img.className = "mana-pip"; img.alt = "{C}"; img.title = "{C}"; img.src = SYMBOLOGY["{C}"] || "";
      wrapper.appendChild(img);
      pill.appendChild(wrapper);
    }
    return pill.outerHTML;
  }
  const wrapper = document.createElement("span");
  wrapper.className = "mana-pips";
  for(const c of ordered){
    const token = `{${c}}`;
    const img = document.createElement("img");
    img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
    wrapper.appendChild(img);
  }
  pill.appendChild(wrapper);
  return pill.outerHTML;
}

function renderColorIdentityPips(card){
  const WUBRG = ["W","U","B","R","G"];
  const identitySet = new Set();
  if(Array.isArray(card.color_identity) && card.color_identity.length){
    for(const c of card.color_identity) identitySet.add(String(c).toUpperCase());
  }
  const pill = document.createElement("span");
  pill.className = "pill-label-pips";
  const label = document.createElement("span");
  label.className = "pip-label"; label.textContent = "Identity:";
  pill.appendChild(label);
  if(!identitySet.size){
    if(String(card.color || "").toUpperCase() === "COLORLESS"){
      const wrapper = document.createElement("span");
      wrapper.className = "mana-pips";
      const img = document.createElement("img");
      img.className = "mana-pip"; img.alt = "{C}"; img.title = "{C}"; img.src = SYMBOLOGY["{C}"] || "";
      wrapper.appendChild(img);
      pill.appendChild(wrapper);
      return pill.outerHTML;
    }
    pill.appendChild(document.createTextNode(" —"));
    return pill.outerHTML;
  }
  // Follow mana cost symbol order first, then WUBRG for remainder (e.g. colours from rules text)
  const ordered = [];
  const seen = new Set();
  if(card.mana_cost){
    const costTokens = String(card.mana_cost).replace(/ \/\/ /g, "").match(/\{[^}]+\}/g) || [];
    for(const tok of costTokens){
      const inner = tok.slice(1, -1).toUpperCase();
      if(WUBRG.includes(inner) && identitySet.has(inner) && !seen.has(inner)){
        seen.add(inner); ordered.push(`{${inner}}`);
      }
    }
  }
  for(const c of WUBRG){
    if(identitySet.has(c) && !seen.has(c)) ordered.push(`{${c}}`);
  }
  const wrapper = document.createElement("span");
  wrapper.className = "mana-pips";
  for(const token of ordered){
    const img = document.createElement("img");
    img.className = "mana-pip"; img.alt = token; img.title = token; img.src = SYMBOLOGY[token] || "";
    wrapper.appendChild(img);
  }
  pill.appendChild(wrapper);
  return pill.outerHTML;
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
    const manaCostHtml = renderManaCost(card.mana_cost);
    node.querySelector(".mana-row").innerHTML = manaCostHtml === "—" ? "—" : `Mana cost: ${manaCostHtml}`;
    const visibleTags = getVisibleTags(card);
    const tagsRow = node.querySelector(".tags-row");
    if(visibleTags.length){
      const isFilteredByTag = parseTagFilterTerms(el.tag?.value).length > 0 && !el.showTagsToggle?.checked;
      tagsRow.textContent = isFilteredByTag ? `Matching tags: ${visibleTags.join(", ")}` : `Tags: ${visibleTags.join(", ")}`;
      tagsRow.style.display = "";
    } else {
      tagsRow.style.display = "none";
    }
    const colorPill = node.querySelector(".color-pill");
    colorPill.innerHTML = renderColorPips(card);
    node.querySelector(".commander-pill").innerHTML = renderColorIdentityPips(card);
    node.querySelector(".include-pill").textContent = `Include %: ${card.include_pct ?? "—"}`;
    node.querySelector(".price-pill").textContent = `SEK: ${formatSek(sekPrice(card))}`;
    node.querySelector(".cmc-pill").textContent = `MV: ${card.cmc ?? "—"}`;
    node.querySelector(".edhrec-link").href = buildEdhrecLink(card);
    node.querySelector(".scryfall-link").href = buildScryfallLink(card);
    node.querySelector(".image-link").href = card.image_url || "#";
    const img = node.querySelector(".card-image");
    img.alt = card.name || "Card image"; img.src = card.image_url || "";
    const flipBtn = node.querySelector(".flip-pill");
    if(card.back_image_url && card.keywords && card.keywords.includes("Transform")){
      flipBtn.style.display = "inline-flex";
      let isFlipped = false;
      flipBtn.addEventListener("click", () => {
        isFlipped = !isFlipped;
        img.src = isFlipped ? card.back_image_url : card.image_url;
        colorPill.innerHTML = renderColorPips(card, isFlipped ? card.back_mana_cost : card.mana_cost);
        flipBtn.textContent = isFlipped ? "↺" : "↻";
      });
    } else {
      flipBtn.style.display = "none";
    }
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
  const commanderText=commanderColors.length ? ` • commander identity ${commanderColors.join("")}` : "";
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

function ensureSetFilterControl(){
  if(el.set) return;
  const nameInput = document.getElementById("nameFilter");
  if(!nameInput?.parentElement) return;
  const label = document.createElement("label");
  label.innerHTML = '<span class="label-title">Set <span class="info-dot" title="Filter by set code shortname, like neo or mh3. Use | for OR and , for AND groups.">i</span></span><input id="setFilter" type="text" placeholder="neo|mh3">';
  nameInput.parentElement.insertAdjacentElement("afterend", label);
  el.set = document.getElementById("setFilter");
}

function resetSearchFilters(){
  for(const control of [el.name, el.set, el.include, el.price, el.tag, el.text, el.typeInclude, el.typeExclude, el.cmcMin, el.cmcMax]){
    if(control) control.value = "";
  }
  if(el.sort) el.sort.value = "include_desc";
  if(el.imageToggle) el.imageToggle.checked = true;
  if(el.showTagsToggle) el.showTagsToggle.checked = false;

  for(const checkbox of document.querySelectorAll('input[name="exactColor"]')) checkbox.checked = false;
  for(const control of [el.commanderW, el.commanderU, el.commanderB, el.commanderR, el.commanderG, document.getElementById("commanderC")]){
    if(control) control.checked = false;
  }

  applyFilters(true);
}

function activateTab(which){
  const isSearch = which==="search";
  el.searchTabBtn.classList.toggle("active",isSearch);
  el.deckCheckTabBtn.classList.toggle("active",!isSearch);
  el.searchTab.classList.toggle("active",isSearch);
  el.deckCheckTab.classList.toggle("active",!isSearch);
}

async function init(){
  ensureSetFilterControl();
  const [cardsResp, symResp] = await Promise.all([fetch("/api/cards"), fetch("/api/symbology")]);
  const cardsData = await cardsResp.json(); const symData = await symResp.json();
  ALL_CARDS = Array.isArray(cardsData.cards) ? cardsData.cards : [];
  for(const card of ALL_CARDS){
    card._oracleTextNorm = normalizeText(card.oracle_text || "");
  }
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

ensureSetFilterControl();

const searchControlIds = [
  "nameFilter",
  "setFilter",
  "includeFilter",
  "priceFilter",
  "typeIncludeFilter",
  "typeExcludeFilter",
  "tagFilter",
  "textFilter",
  "cmcMinFilter",
  "cmcMaxFilter",
  "sortFilter",
  "imageToggle",
  "showTagsToggle",
  "commanderW",
  "commanderU",
  "commanderB",
  "commanderR",
  "commanderG",
  "commanderC",
];

for(const id of searchControlIds){
  const control = document.getElementById(id);
  if(!control) continue;
  control.addEventListener("keydown", (event) => {
    if(event.key === "Enter") applyFilters(true);
  });
}

document.querySelectorAll('input[name="exactColor"]').forEach(checkbox=>{
  checkbox.addEventListener("keydown", (event) => {
    if(event.key === "Enter") applyFilters(true);
  });
});

if(el.searchFiltersBtn) el.searchFiltersBtn.addEventListener("click", () => applyFilters(true));
if(el.resetFiltersBtn) el.resetFiltersBtn.addEventListener("click", resetSearchFilters);

// Toggles that only affect rendering — re-render immediately without re-filtering
if(el.imageToggle) el.imageToggle.addEventListener("change", () => renderCards(currentFilteredSorted));
if(el.showTagsToggle) el.showTagsToggle.addEventListener("change", () => renderCards(currentFilteredSorted));

el.deckThresholdMode.addEventListener("change", updateDeckThresholdLabel);
updateDeckThresholdLabel();
el.nextPageBtn.addEventListener("click",nextPage); el.nextPageBtnBottom.addEventListener("click",nextPage);
el.prevPageBtn.addEventListener("click",prevPage); el.prevPageBtnBottom.addEventListener("click",prevPage);
el.searchTabBtn.addEventListener("click",()=>activateTab("search")); el.deckCheckTabBtn.addEventListener("click",()=>activateTab("deck"));
el.fetchDeckBtn.addEventListener("click",fetchDecklistFromUrl); el.checkDeckBtn.addEventListener("click",checkDeck);
init();
