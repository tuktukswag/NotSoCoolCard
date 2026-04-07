let ALL_CARDS = [];
let CARD_LOOKUP = new Map();
let SYMBOLOGY = {};
const PAGE_SIZE = 100;
let currentPage = 1;
let currentFilteredSorted = [];
let USD_SEK_RATE = null;

const ALWAYS_IGNORED_BASIC_LANDS = new Set([
  "plains", "island", "swamp", "mountain", "forest", "wastes",
  "snow covered plains", "snow covered island", "snow covered swamp",
  "snow covered mountain", "snow covered forest"
]);

const el = {
  searchTabBtn: document.getElementById("searchTabBtn"),
  deckCheckTabBtn: document.getElementById("deckCheckTabBtn"),
  searchTab: document.getElementById("searchTab"),
  deckCheckTab: document.getElementById("deckCheckTab"),
  name: document.getElementById("nameFilter"),
  color: document.getElementById("colorFilter"),
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
  deckIncludeFilter: document.getElementById("deckIncludeFilter"),
  excludeLandsCheckbox: document.getElementById("excludeLandsCheckbox"),
  checkDeckBtn: document.getElementById("checkDeckBtn"),
  deckInfoBox: document.getElementById("deckInfoBox"),
  deckResults: document.getElementById("deckResults"),
};

function asArray(value){ if(Array.isArray(value)) return value; if(!value) return []; return [value]; }
function normalizeText(value){ return String(value || "").toLowerCase().replace(/[^\w\s']/g," ").replace(/\s+/g," ").trim(); }
function parseCommaTerms(value){ return String(value || "").split(",").map(v=>normalizeText(v)).filter(Boolean); }
function usdPrice(card){ const usd=card?.price?.usd; if(usd===null||usd===undefined||usd==="") return null; const v=Number(usd); return Number.isFinite(v)?v:null; }
function sekPrice(card){ const usd=usdPrice(card); if(usd===null||USD_SEK_RATE===null) return null; const v=usd*USD_SEK_RATE; return Number.isFinite(v)?v:null; }
function formatSek(value){ if(value===null||value===undefined) return "—"; return new Intl.NumberFormat("sv-SE",{minimumFractionDigits:2, maximumFractionDigits:2}).format(value); }
function buildCardLookup(cards){ const map=new Map(); for(const card of cards){ const key=normalizeText(card.name); if(key && !map.has(key)) map.set(key, card);} return map; }
function isAlwaysIgnoredBasicLandName(name){ return ALWAYS_IGNORED_BASIC_LANDS.has(normalizeText(name)); }

function getCommanderIdentity(){ const c=[]; if(el.commanderW.checked)c.push("W"); if(el.commanderU.checked)c.push("U"); if(el.commanderB.checked)c.push("B"); if(el.commanderR.checked)c.push("R"); if(el.commanderG.checked)c.push("G"); return c; }
function cardFitsCommanderIdentity(card, commanderColors){ if(!commanderColors.length) return true; const cardColors=Array.isArray(card.color_identity)&&card.color_identity.length?card.color_identity:(card.color&&card.color!=="COLORLESS"?card.color.split(""):[]); return cardColors.every(color=>commanderColors.includes(color)); }
function manaPassesFilter(cmc){ const f=el.cmc.value===""?null:Number(el.cmc.value); if(f===null) return true; const c=Number(cmc ?? Infinity); const mode=el.cmcMode.value; if(mode==="eq") return c===f; if(mode==="gte") return c>=f; return c<=f; }
function typePassesFilter(cardType){ const txt=normalizeText(cardType); const include=parseCommaTerms(el.typeInclude.value); const exclude=parseCommaTerms(el.typeExclude.value); if(include.length && !include.some(term=>txt.includes(term))) return false; if(exclude.some(term=>txt.includes(term))) return false; return true; }

function cardMatches(card){
  const nameFilter=normalizeText(el.name.value);
  const colorFilter=el.color.value.trim();
  const tagFilter=normalizeText(el.tag.value);
  const includeFilter=el.include.value===""?null:Number(el.include.value);
  const priceFilter=el.price.value===""?null:Number(el.price.value);
  const commanderColors=getCommanderIdentity();
  const name=normalizeText(card.name);
  const color=String(card.color || "COLORLESS");
  const tags=asArray(card.tags).join(" | ").toLowerCase();
  const includePct=Number(card.include_pct ?? Infinity);
  const sek=sekPrice(card);
  if(nameFilter && !name.includes(nameFilter)) return false;
  if(colorFilter && color!==colorFilter) return false;
  if(tagFilter && !tags.includes(tagFilter)) return false;
  if(includeFilter!==null && !(includePct<=includeFilter)) return false;
  if(priceFilter!==null && !(sek!==null && sek<=priceFilter)) return false;
  if(!manaPassesFilter(card.cmc)) return false;
  if(!typePassesFilter(card.card_type)) return false;
  if(el.limitCommander.checked && !cardFitsCommanderIdentity(card, commanderColors)) return false;
  return true;
}

function sortCards(cards){
  const mode=el.sort.value;
  const sorted=[...cards];
  sorted.sort((a,b)=>{
    if(mode==="include_desc") return (b.include_pct??-Infinity)-(a.include_pct??-Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="include_asc") return (a.include_pct??Infinity)-(b.include_pct??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="price_asc") return (sekPrice(a)??Infinity)-(sekPrice(b)??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="price_desc") return (sekPrice(b)??-Infinity)-(sekPrice(a)??-Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="name_asc") return String(a.name).localeCompare(String(b.name));
    if(mode==="cmc_asc") return (a.cmc??Infinity)-(b.cmc??Infinity)||String(a.name).localeCompare(String(b.name));
    if(mode==="edhrec_rank_asc") return (a.edhrec_rank??Infinity)-(b.edhrec_rank??Infinity)||String(a.name).localeCompare(String(b.name));
    return 0;
  });
  return sorted;
}

function updatePaginationUI(totalCards){
  const totalPages=Math.max(1, Math.ceil(totalCards/PAGE_SIZE));
  const startIndex=totalCards===0?0:(currentPage-1)*PAGE_SIZE+1;
  const endIndex=Math.min(currentPage*PAGE_SIZE,totalCards);
  const text=totalCards===0?"Page 1 of 1 • 0 results":`Page ${currentPage} of ${totalPages} • showing ${startIndex}-${endIndex} of ${totalCards}`;
  el.pageSummary.textContent=text; el.pageSummaryBottom.textContent=text;
  const disablePrev=currentPage<=1; const disableNext=currentPage>=totalPages||totalCards===0;
  el.prevPageBtn.disabled=disablePrev; el.prevPageBtnBottom.disabled=disablePrev; el.nextPageBtn.disabled=disableNext; el.nextPageBtnBottom.disabled=disableNext;
}

function renderManaCost(manaCost){
  if(!manaCost) return "Mana cost: —";
  const wrapper=document.createElement("span"); wrapper.className="mana-pips";
  const tokens=String(manaCost).match(/\{[^}]+\}/g)||[];
  if(!tokens.length){ wrapper.textContent=manaCost; return wrapper.outerHTML; }
  for(const token of tokens){ const img=document.createElement("img"); img.className="mana-pip"; img.alt=token; img.title=token; img.src=SYMBOLOGY[token]||""; wrapper.appendChild(img); }
  return wrapper.outerHTML;
}

function renderCards(cards){
  el.results.innerHTML="";
  if(!cards.length){ const empty=document.createElement("div"); empty.className="empty-state"; empty.textContent="No cards match your filters."; el.results.appendChild(empty); updatePaginationUI(0); return; }
  const totalPages=Math.max(1, Math.ceil(cards.length/PAGE_SIZE)); if(currentPage>totalPages) currentPage=totalPages; if(currentPage<1) currentPage=1;
  const start=(currentPage-1)*PAGE_SIZE; const pageCards=cards.slice(start,start+PAGE_SIZE);
  const showImages=el.imageToggle.checked; const commanderColors=getCommanderIdentity(); const commanderLabel=commanderColors.length?commanderColors.join(""):"Any";
  for(const card of pageCards){
    const node=el.template.content.cloneNode(true);
    const imageWrap=node.querySelector(".image-wrap"); const image=node.querySelector(".card-image"); const name=node.querySelector(".card-name");
    const meta=node.querySelector(".meta-row"); const mana=node.querySelector(".mana-row"); const priceRow=node.querySelector(".price-row"); const tags=node.querySelector(".tags-row");
    const colorPill=node.querySelector(".color-pill"); const includePill=node.querySelector(".include-pill"); const cmcPill=node.querySelector(".cmc-pill"); const commanderPill=node.querySelector(".commander-pill"); const pricePill=node.querySelector(".price-pill");
    const edhrecLink=node.querySelector(".edhrec-link"); const scryfallLink=node.querySelector(".scryfall-link"); const imageLink=node.querySelector(".image-link");
    const sek=sekPrice(card); const sekFoil=card?.price?.usd_foil?Number(card.price.usd_foil)*USD_SEK_RATE:null; const eur=card?.price?.eur||"—";
    name.textContent=card.name||"Unknown";
    meta.textContent=`${card.card_type||"—"}${card.edhrec_rank ? " • EDHREC rank "+card.edhrec_rank : ""}`;
    mana.innerHTML=`Mana cost: ${renderManaCost(card.mana_cost)} • Mana value: ${card.cmc ?? "—"}`;
    priceRow.textContent=`Price: SEK ${formatSek(sek)} • Foil SEK ${formatSek(sekFoil)} • EUR ${eur}`;
    tags.textContent=`Tags: ${asArray(card.tags).length ? asArray(card.tags).join(", ") : "—"}`;
    colorPill.textContent=`Color: ${card.color||"COLORLESS"}`; includePill.textContent=`Include %: ${card.include_pct ?? "—"}`; cmcPill.textContent=`MV: ${card.cmc ?? "—"}`; commanderPill.textContent=`Commander: ${commanderLabel}`; pricePill.textContent=`SEK: ${formatSek(sek)}`;
    edhrecLink.href=card.edhrec_link||"#"; scryfallLink.href=card.scryfall_link||"#"; imageLink.href=card.image_url||"#";
    image.alt=card.name||"Card image"; image.src=card.image_url||""; if(!showImages||!card.image_url) imageWrap.style.display="none";
    el.results.appendChild(node);
  }
  updatePaginationUI(cards.length);
}

function applyFilters(resetPage=false){
  if(resetPage) currentPage=1;
  currentFilteredSorted=sortCards(ALL_CARDS.filter(cardMatches));
  renderCards(currentFilteredSorted);
  const commanderColors=getCommanderIdentity();
  const commanderText=el.limitCommander.checked ? ` • commander identity ${commanderColors.length ? commanderColors.join("") : "none selected"}` : "";
  el.summary.textContent=`${currentFilteredSorted.length} / ${ALL_CARDS.length} cards shown${commanderText}`;
}

function nextPage(){ const totalPages=Math.max(1,Math.ceil(currentFilteredSorted.length/PAGE_SIZE)); if(currentPage<totalPages){ currentPage+=1; renderCards(currentFilteredSorted); window.scrollTo({top:0, behavior:"smooth"});} }
function prevPage(){ if(currentPage>1){ currentPage-=1; renderCards(currentFilteredSorted); window.scrollTo({top:0, behavior:"smooth"});} }

function parseDecklist(text){
  const entries=[]; const lines=String(text||"").split(/\r?\n/);
  for(const rawLine of lines){
    const line=rawLine.trim(); if(!line||line.startsWith("#")||line.startsWith("//")) continue;
    const lower=line.toLowerCase(); if(["commander","companions","deck","mainboard","sideboard","maybeboard"].includes(lower)) continue;
    const match=line.match(/^(\d+)\s*x?\s+(.+)$/i); if(!match) continue;
    let qty=Number(match[1]); let name=match[2].trim();
    name=name.replace(/\s+\([A-Za-z0-9]{2,6}\)\s+\d+[A-Za-z]?$/g,"").trim();
    name=name.replace(/\s+\[[^\]]+\]\s*$/g,"").trim();
    name=name.replace(/\s+\*[^*]+\*\s*$/g,"").trim();
    name=name.replace(/\s+\^[^^]+\^[^^]*$/g,"").trim();
    if(qty>0 && name) entries.push({quantity:qty, name, normalized:normalizeText(name)});
  }
  return entries;
}

function renderDeckCheckResults(result){
  const container=document.createElement("div"); container.className="deck-check-report";
  const summary=document.createElement("div"); summary.className="deck-summary";
  summary.innerHTML=`<div>Total cards: <strong>${result.totalCards}</strong></div><div>Checked cards: <strong>${result.checkedCount}</strong></div><div>Ignored cards: <strong>${result.ignoredCount}</strong></div><div>Offenders: <strong>${result.offenders.length}</strong></div>`;
  container.appendChild(summary);

  if(result.blocked){
    const blocked=document.createElement("div"); blocked.className="warning-box"; blocked.textContent=result.message; container.appendChild(blocked); return container;
  }

  if(!result.offenders.length){
    const ok=document.createElement("div"); ok.className="success-box"; ok.textContent=`Deck passed. All checked cards are at or below ${result.threshold}% inclusion.`; container.appendChild(ok);
  }

  if(result.offenders.length){
    const section=document.createElement("section");
    section.innerHTML="<h3>Cards failing the threshold</h3>";
    const list=document.createElement("ul"); list.className="report-list";
    for(const offender of result.offenders){
      const li=document.createElement("li");
      li.textContent = offender.assumed
        ? `${offender.quantity} ${offender.name} — assumed above ${result.threshold}% because it is not in the current dataset`
        : `${offender.quantity} ${offender.name} — ${offender.include_pct}%`;
      list.appendChild(li);
    }
    section.appendChild(list);
    container.appendChild(section);
  }

  if(result.ignored.length){
    const section=document.createElement("section");
    section.innerHTML="<h3>Ignored cards</h3>";
    const list=document.createElement("ul"); list.className="report-list";
    for(const ignored of result.ignored){
      const li=document.createElement("li");
      li.textContent=`${ignored.quantity} ${ignored.name} — ${ignored.reason}`;
      list.appendChild(li);
    }
    section.appendChild(list);
    container.appendChild(section);
  }

  return container;
}

function checkDeck(){
  const entries=parseDecklist(el.decklistInput.value); const totalCards=entries.reduce((sum,entry)=>sum+entry.quantity,0); el.deckResults.innerHTML="";
  if(!entries.length){ el.deckInfoBox.textContent="No valid decklist lines found."; return; }
  el.deckInfoBox.textContent=`Deck contains ${totalCards} cards.`;
  const threshold=Number(el.deckIncludeFilter.value||2); const excludeLands=el.excludeLandsCheckbox.checked;
  if(totalCards>100){
    el.deckResults.appendChild(renderDeckCheckResults({blocked:true,message:`Deck has ${totalCards} cards. The checker will not run for decklists above 100 cards.`,totalCards,checkedCount:0,ignoredCount:0,offenders:[],ignored:[],threshold}));
    return;
  }

  const offenders=[]; const ignored=[]; let checkedCount=0;

  for(const entry of entries){
    if(isAlwaysIgnoredBasicLandName(entry.name)){
      ignored.push({quantity: entry.quantity, name: entry.name, reason: "basic land"});
      continue;
    }

    const card=CARD_LOOKUP.get(entry.normalized);

    if(!card){
      offenders.push({quantity: entry.quantity, name: entry.name, assumed: true});
      checkedCount += 1;
      continue;
    }

    const isLand=normalizeText(card.card_type).includes("land");
    if(excludeLands && isLand){
      ignored.push({quantity: entry.quantity, name: card.name, reason: "land excluded"});
      continue;
    }

    checkedCount += 1;

    const includePct=Number(card.include_pct ?? Infinity);
    if(!(includePct<=threshold)) offenders.push({quantity:entry.quantity, name:card.name, include_pct:includePct, assumed:false});
  }

  el.deckResults.appendChild(renderDeckCheckResults({
    blocked:false,
    totalCards,
    checkedCount,
    ignoredCount: ignored.length,
    offenders,
    ignored,
    threshold
  }));
}

async function fetchDecklistFromUrl(){
  const url=el.deckUrlInput.value.trim();
  if(!url){ el.deckInfoBox.textContent="Paste a deck URL first."; return; }
  el.deckInfoBox.textContent="Fetching decklist…";
  try{
    const response=await fetch("/api/deck-resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
    const data=await response.json();
    if(!response.ok || !data.ok) throw new Error(data.error || "Could not fetch decklist");
    el.decklistInput.value=data.decklist;
    const entries=parseDecklist(data.decklist);
    const totalCards=entries.reduce((sum,entry)=>sum+entry.quantity,0);
    el.deckInfoBox.textContent=`Fetched ${totalCards} cards from ${data.source}.`;
  }catch(error){
    el.deckInfoBox.textContent=error.message || "Could not fetch decklist.";
  }
}

function activateTab(which){
  const isSearch=which==="search";
  el.searchTabBtn.classList.toggle("active",isSearch);
  el.deckCheckTabBtn.classList.toggle("active",!isSearch);
  el.searchTab.classList.toggle("active",isSearch);
  el.deckCheckTab.classList.toggle("active",!isSearch);
}

async function init(){
  const [cardsResp, symResp]=await Promise.all([fetch("/api/cards"), fetch("/api/symbology")]);
  const cardsData=await cardsResp.json(); const symData=await symResp.json();
  ALL_CARDS=Array.isArray(cardsData.cards)?cardsData.cards:[]; CARD_LOOKUP=buildCardLookup(ALL_CARDS);
  USD_SEK_RATE=cardsData?.meta?.usd_sek_rate!==undefined && cardsData?.meta?.usd_sek_rate!==null ? Number(cardsData.meta.usd_sek_rate) : null;
  SYMBOLOGY=symData?.symbols || {};
  applyFilters(true);
}

for(const control of [el.name, el.color, el.include, el.price, el.tag, el.typeInclude, el.typeExclude, el.cmc, el.cmcMode, el.sort, el.imageToggle, el.limitCommander, el.commanderW, el.commanderU, el.commanderB, el.commanderR, el.commanderG]){
  control.addEventListener("input",()=>applyFilters(true)); control.addEventListener("change",()=>applyFilters(true));
}
el.nextPageBtn.addEventListener("click",nextPage); el.nextPageBtnBottom.addEventListener("click",nextPage); el.prevPageBtn.addEventListener("click",prevPage); el.prevPageBtnBottom.addEventListener("click",prevPage);
el.searchTabBtn.addEventListener("click",()=>activateTab("search")); el.deckCheckTabBtn.addEventListener("click",()=>activateTab("deck"));
el.fetchDeckBtn.addEventListener("click",fetchDecklistFromUrl); el.checkDeckBtn.addEventListener("click",checkDeck);
init();
