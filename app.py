from datetime import datetime, timedelta
from typing import Dict, List
import threading
import time

from flask import Flask, jsonify, render_template, request, url_for

from config import TIMEZONE
from scraper import (
    Article,
    TOPIC_CONFIG,
    fetch_dashboard_articles,
    Quote,
    fetch_quotes,
    NoticiasAgricolasScraper,
    normalize_url,
)

app = Flask(__name__)

NEWS_REFRESH_INTERVAL_SECONDS = 60
QUOTES_REFRESH_INTERVAL_SECONDS = 60
news_cache: Dict[str, object] = {"articles": [], "generated_at": None}
quotes_cache: Dict[str, object] = {"quotes": [], "generated_at": None}
news_lock = threading.Lock()
quotes_lock = threading.Lock()


def serialize_article(article: Article) -> Dict[str, object]:
    config = TOPIC_CONFIG[article.topic_key]
    return {
        "source": getattr(article, "source", "Notícias Agrícolas"),
        "topic_key": article.topic_key,
        "topic_label": article.topic_label,
        "title": article.title,
        "summary": article.summary,
        "url": article.url,
        "image_url": article.image_url,
        "published_at": article.iso_published_at,
        "published_label": article.published_at.strftime("%d/%m/%Y %H:%M"),
        "color": config["color"],
    }


def serialize_quote(q: Quote) -> Dict[str, object]:
    return {
        "key": q.key,
        "label": q.label,
        "value": q.value,
        "change": q.change,
        "unit": q.unit,
        "source": q.source,
    }


def get_cached_articles(force_refresh: bool = False) -> Dict[str, object]:
    now = datetime.now(TIMEZONE)
    if force_refresh:
        with news_lock:
            prev = list(news_cache.get("articles", []))
            fresh = fetch_dashboard_articles()
            completed = _complete_with_previous_sources(fresh, prev, total=15)
            news_cache["articles"] = completed
            news_cache["generated_at"] = now
    return {"articles": news_cache["articles"], "generated_at": news_cache["generated_at"]}


def get_cached_quotes(force_refresh: bool = False) -> Dict[str, object]:
    now = datetime.now(TIMEZONE)
    if force_refresh:
        with quotes_lock:
            quotes_cache["quotes"] = fetch_quotes()
            quotes_cache["generated_at"] = now
    return {"quotes": quotes_cache["quotes"], "generated_at": quotes_cache["generated_at"]}


def _refresh_news_loop():
    while True:
        try:
            with news_lock:
                news_cache["articles"] = fetch_dashboard_articles()
                news_cache["generated_at"] = datetime.now(TIMEZONE)
        except Exception:
            pass
        time.sleep(max(1, NEWS_REFRESH_INTERVAL_SECONDS))


def _refresh_quotes_loop():
    while True:
        try:
            with quotes_lock:
                quotes_cache["quotes"] = fetch_quotes()
                quotes_cache["generated_at"] = datetime.now(TIMEZONE)
        except Exception:
            pass
        time.sleep(max(1, QUOTES_REFRESH_INTERVAL_SECONDS))


def start_background_refreshers():
    t1 = threading.Thread(target=_refresh_news_loop, daemon=True)
    t2 = threading.Thread(target=_refresh_quotes_loop, daemon=True)
    t1.start()
    t2.start()


def prime_cache_on_startup():
    now = datetime.now(TIMEZONE)
    # Prime rápido de notícias usando Notícias Agrícolas por temas
    try:
        fast = _fast_prime_articles_na(limit=6)
        with news_lock:
            news_cache["articles"] = fast
            news_cache["generated_at"] = now
    except Exception:
        pass
    # Prime de cotações em segundo plano para não bloquear primeira renderização
    refresh_quotes_async_once()
    # Disparar refresh completo em background para enriquecer a página
    refresh_news_async_once()


def refresh_news_async_once():
    def _run():
        try:
            with news_lock:
                news_cache["articles"] = fetch_dashboard_articles()
                news_cache["generated_at"] = datetime.now(TIMEZONE)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def refresh_quotes_async_once():
    def _run():
        try:
            with quotes_lock:
                quotes_cache["quotes"] = fetch_quotes()
                quotes_cache["generated_at"] = datetime.now(TIMEZONE)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def _has_external_sources() -> bool:
    arts = news_cache.get("articles") or []
    try:
        return any(getattr(a, "source", "") != "Notícias Agrícolas" for a in arts)
    except Exception:
        return False


def _complete_with_previous_sources(fresh: List[Article], prev: List[Article], total: int = 15) -> List[Article]:
    by_url = set(normalize_url(a.url) for a in fresh)
    def add_if_needed(seq: List[Article], out: List[Article]):
        for a in seq:
            if normalize_url(a.url) in by_url:
                continue
            out.append(a)
            by_url.add(normalize_url(a.url))
            if len(out) >= total:
                break
    out = list(fresh)
    sources_present = {getattr(a, "source", "") for a in out}
    required = {"Notícias Agrícolas", "Global Crop Protection", "Agrolink"}
    missing = [s for s in required if s not in sources_present]
    for s in missing:
        add_if_needed([a for a in prev if getattr(a, "source", "") == s], out)
        if len(out) >= total:
            break
    if len(out) < total:
        add_if_needed(prev, out)
    return out[:total]


def _fast_prime_articles_na(limit: int = 9) -> List[Article]:
    na = NoticiasAgricolasScraper()
    topics = ["soja", "milho", "cafe", "defensivos", "fertilizantes", "irrigacao"]
    collected: List[Article] = []
    for topic in topics:
        try:
            items = na._fetch_topic_articles(topic, max_results=2)
            for art in items:
                if any(x.url == art.url for x in collected):
                    continue
                collected.append(art)
                if len(collected) >= limit:
                    break
        except Exception:
            continue
        if len(collected) >= limit:
            break
    return collected


@app.route("/")
def index():
    payload = get_cached_articles()
    qpayload = get_cached_quotes()
    articles = payload["articles"]
    articles = (articles[:15] if _has_external_sources() else articles[:9])

    serialized_articles = [serialize_article(article) for article in articles]
    serialized_quotes = [serialize_quote(q) for q in qpayload["quotes"]]
    return render_template(
        "index.html",
        initial_articles=serialized_articles,
        initial_quotes=serialized_quotes,
        generated_at=payload["generated_at"],
        refresh_interval_seconds=NEWS_REFRESH_INTERVAL_SECONDS,
    )


@app.route("/api/news", methods=["GET"])
def api_news():
    if request.args.get("refresh") == "true":
        if not _has_external_sources():
            payload = get_cached_articles(force_refresh=True)
        else:
            refresh_news_async_once()
            payload = get_cached_articles()
    else:
        payload = get_cached_articles()
    articles: List[Article] = payload["articles"]
    articles = (articles[:15] if _has_external_sources() else articles[:9])

    return jsonify(
        {
            "generated_at": (payload["generated_at"] or datetime.now(TIMEZONE)).isoformat(),
            "articles": [serialize_article(article) for article in articles],
        }
    )


@app.route("/api/quotes", methods=["GET"])
def api_quotes():
    if request.args.get("refresh") == "true":
        refresh_quotes_async_once()
    payload = get_cached_quotes()
    quotes: List[Quote] = payload["quotes"]
    return jsonify({
        "generated_at": (payload["generated_at"] or datetime.now(TIMEZONE)).isoformat(),
        "quotes": [serialize_quote(q) for q in quotes],
    })


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    payload = get_cached_articles(force_refresh=True)
    generated_at = payload["generated_at"] or datetime.now(TIMEZONE)
    dashboard_image_url = url_for("static", filename="img/dashboard_email.png", _external=True)
    email_html = render_template(
        "email_template.html",
        generated_at=generated_at,
        dashboard_image_url=dashboard_image_url,
    )

    try:
        send_outlook_email(email_html)
    except Exception as exc:  # pragma: no cover
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({"status": "ok"})


def send_outlook_email(html_body: str) -> None:
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pywin32 não está instalado ou o Outlook não está disponível nesta máquina."
        ) from exc

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.Subject = f"Boletim de Notícias Agrícolas - {datetime.now().strftime('%d/%m/%Y')}"
    mail.HTMLBody = html_body
    mail.Display()


prime_cache_on_startup()
start_background_refreshers()

if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=5000, debug=True)
