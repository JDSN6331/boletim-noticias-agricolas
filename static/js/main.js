const cardsGrid = document.getElementById("cards-grid");
const lastUpdateEl = document.getElementById("last-update");
const refreshBtn = document.getElementById("refresh-btn");
const emailBtn = document.getElementById("email-btn");
const cardTemplate = document.getElementById("card-template");
const toastEl = document.getElementById("toast");
const tickerTrack = document.getElementById("ticker-track");
const updateStatusEl = document.getElementById("update-status");
let REFRESH_INTERVAL_SECONDS = 300;
let INITIAL_QUOTES = [];
const sourcesAwaitEl = document.getElementById("sources-await");

const DATE_FORMATTER = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
});
const DATETIME_FORMATTER = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: "America/Sao_Paulo",
});

function renderCards(articles) {
  cardsGrid.innerHTML = "";
  if (!articles.length) {
    cardsGrid.innerHTML =
      '<div class="empty-state glass-surface"><p>Nenhuma notícia encontrada nos últimos 7 dias.</p></div>';
    return;
  }

  articles.forEach((article) => {
    const card = cardTemplate.content.cloneNode(true);
    const img = card.querySelector("img");
    const topic = card.querySelector(".card-topic");
    const dateEl = card.querySelector(".card-date");
    const sourceEl = card.querySelector(".card-source");
    const titleEl = card.querySelector("h3");
    const summaryEl = card.querySelector(".card-summary");
    const linkEl = card.querySelector(".card-link");
    const cardRoot = card.querySelector(".news-card");

    img.src = article.image_url;
    img.alt = article.title;
    topic.textContent = article.topic_label;
    topic.style.backgroundColor = article.color;
    dateEl.textContent = `Publicado em ${formatDateLabel(article.published_at)}`;
    sourceEl.textContent = `Fonte: ${article.source}`;
    titleEl.textContent = article.title;
    summaryEl.textContent = article.summary;
    linkEl.href = article.url;
    cardRoot.style.setProperty("--topic-color", article.color);

    cardsGrid.appendChild(card);
  });
  updateAwaitingLabel(articles);
}

function formatDateLabel(dateStr) {
  try {
    const date = new Date(dateStr);
    return DATE_FORMATTER.format(date);
  } catch (err) {
    return dateStr;
  }
}

function updateTimestamp(isoString) {
  if (!isoString) return;
  lastUpdateEl.textContent = DATETIME_FORMATTER.format(new Date(isoString));
}

function renderTicker(quotes) {
  if (!tickerTrack) return;
  tickerTrack.innerHTML = "";
  const items = quotes && quotes.length ? quotes : [];
  const repeat = 1;
  const makeItem = (q) => {
    const span = document.createElement("span");
    span.className = "ticker-item";
    const lab = document.createElement("span");
    lab.className = "label";
    lab.textContent = q.label + ":";
    const val = document.createElement("span");
    val.className = "value";
    const unit = (q.unit || "").trim();
    const v = (q.value || "--").trim();
    val.textContent = unit ? `${unit} ${v}` : v;
    const legend = document.createElement("span");
    legend.className = "legend";
    legend.textContent = (q.source || "").trim();
    const ch = document.createElement("span");
    ch.className = (q.change || "").startsWith("-") ? "down" : "up";
    ch.textContent = q.change || "";
    span.appendChild(lab);
    span.appendChild(val);
    if (legend.textContent) span.appendChild(legend);
    if (q.change) span.appendChild(ch);
    return span;
  };
  items.forEach((q) => tickerTrack.appendChild(makeItem(q)));
  const trackWidth = tickerTrack.scrollWidth;
  const viewportWidth = window.innerWidth;
  const totalDistance = trackWidth + viewportWidth;
  const durationSec = Math.round(totalDistance / 80);
  tickerTrack.style.setProperty("--track-width", `${trackWidth}px`);
  tickerTrack.style.setProperty("--marquee-duration", `${durationSec}s`);
}

function showUpdateStatus(message) {
  if (!updateStatusEl) return;
  updateStatusEl.textContent = message;
  updateStatusEl.classList.add("show");
}

function hideUpdateStatus() {
  if (!updateStatusEl) return;
  updateStatusEl.classList.remove("show");
}

async function loadNews(refresh = false) {
  if (refresh) showUpdateStatus("Atualizando notícias...");
  setLoadingState(refreshBtn, true, "Atualizando...");
  try {
    const url = refresh ? "/api/news?refresh=true" : "/api/news";
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error("Falha ao buscar notícias");
    }
    const data = await response.json();
    renderCards(data.articles);
    updateTimestamp(data.generated_at);
    showToast("Painel atualizado com sucesso!");
    if (refresh) {
      setTimeout(async () => {
        try {
          const res = await fetch("/api/news");
          const payload = await res.json();
          renderCards(payload.articles);
          updateTimestamp(payload.generated_at);
        } catch (_) {}
        hideUpdateStatus();
      }, 20000);
    }
  } catch (error) {
    console.error(error);
    showToast("Não foi possível atualizar as notícias.", "error");
  } finally {
    setLoadingState(refreshBtn, false, "Atualizar Notícias");
    if (!refresh) hideUpdateStatus();
  }
}

async function sendEmail() {
  setLoadingState(emailBtn, true, "Gerando HTML...");
  try {
    const response = await fetch("/api/send-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || "Erro ao gerar e-mail");
    }
    showToast("E-mail aberto no Outlook. Revise e envie!");
  } catch (error) {
    console.error(error);
    showToast(error.message || "Não foi possível gerar o e-mail.", "error");
  } finally {
    setLoadingState(emailBtn, false, "Gerar HTML para E-mail");
  }
}

async function loadQuotes(force = false) {
  if (force) showUpdateStatus("Atualizando cotações...");
  try {
    const res = await fetch(`/api/quotes${force ? "?refresh=true" : ""}`);
    const data = await res.json();
    renderTicker(data.quotes || []);
  } catch (err) {
    renderTicker(INITIAL_QUOTES || []);
  } finally {
    if (force) hideUpdateStatus();
  }
}

function setLoadingState(button, isLoading, defaultLabel) {
  if (!button) return;
  button.disabled = isLoading;
  button.textContent = isLoading ? "Aguarde..." : defaultLabel;
}

function showToast(message, variant = "success") {
  toastEl.textContent = message;
  toastEl.className = `toast ${variant}`;
  toastEl.classList.add("visible");
  setTimeout(() => toastEl.classList.remove("visible"), 3500);
}

function parseJSONScript(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  try { return JSON.parse(el.textContent); } catch (_) { return null; }
}

function hydrateInitialState() {
  const articles = parseJSONScript("initial-articles") || [];
  const quotes = parseJSONScript("initial-quotes") || [];
  const meta = parseJSONScript("initial-meta") || {};
  const generatedAt = meta.generated_at || "";
  const intervalSec = Number(meta.refresh_interval_seconds) || 300;
  REFRESH_INTERVAL_SECONDS = intervalSec;
  INITIAL_QUOTES = quotes;
  renderCards(articles);
  renderTicker(quotes);
  if (generatedAt) {
    updateTimestamp(generatedAt);
  }
  updateAwaitingLabel(articles);
}

document.addEventListener("DOMContentLoaded", () => {
  hydrateInitialState();
  loadQuotes(false);
  loadNews(true);
  // Atualização automática usando o intervalo configurado
  setInterval(() => loadNews(true), REFRESH_INTERVAL_SECONDS * 1000);
  setInterval(() => loadQuotes(true), REFRESH_INTERVAL_SECONDS * 1000);
  emailBtn.addEventListener("click", sendEmail);
});
function updateAwaitingLabel(articles) {
  if (!sourcesAwaitEl) return;
  const hasOnlyNA = articles.length > 0 && articles.every((a) => (a.source || "") === "Notícias Agrícolas");
  sourcesAwaitEl.style.display = hasOnlyNA ? "block" : "none";
}
