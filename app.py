from datetime import datetime, timedelta
from typing import Dict, List
import threading
import time
import os
import json

from flask import Flask, jsonify, render_template, request

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
STATIC_DATA_DIR = os.path.join(app.static_folder or "static", "data")

NEWS_REFRESH_INTERVAL_SECONDS = 300
QUOTES_REFRESH_INTERVAL_SECONDS = 300
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


def _ensure_static_data_dir() -> None:
    try:
        os.makedirs(STATIC_DATA_DIR, exist_ok=True)
    except Exception:
        pass


def _write_json(filename: str, payload: Dict[str, object]) -> None:
    try:
        _ensure_static_data_dir()
        path = os.path.join(STATIC_DATA_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def _export_news_json(articles: List[Article], generated_at: datetime) -> None:
    try:
        data = {
            "generated_at": (generated_at or datetime.now(TIMEZONE)).isoformat(),
            "articles": [serialize_article(a) for a in articles],
        }
        _write_json("news.json", data)
    except Exception:
        pass


def _export_quotes_json(quotes: List[Quote], generated_at: datetime) -> None:
    try:
        data = {
            "generated_at": (generated_at or datetime.now(TIMEZONE)).isoformat(),
            "quotes": [serialize_quote(q) for q in quotes],
        }
        _write_json("quotes.json", data)
    except Exception:
        pass


def get_cached_articles(force_refresh: bool = False) -> Dict[str, object]:
    now = datetime.now(TIMEZONE)
    if force_refresh:
        with news_lock:
            prev = list(news_cache.get("articles", []))
            fresh = fetch_dashboard_articles()
            completed = _complete_with_previous_sources(fresh, prev, total=15)
            news_cache["articles"] = completed
            news_cache["generated_at"] = now
            _export_news_json(news_cache["articles"], news_cache["generated_at"]) 
    return {"articles": news_cache["articles"], "generated_at": news_cache["generated_at"]}


def get_cached_quotes(force_refresh: bool = False) -> Dict[str, object]:
    now = datetime.now(TIMEZONE)
    if force_refresh:
        with quotes_lock:
            quotes_cache["quotes"] = fetch_quotes()
            quotes_cache["generated_at"] = now
            _export_quotes_json(quotes_cache["quotes"], quotes_cache["generated_at"]) 
    return {"quotes": quotes_cache["quotes"], "generated_at": quotes_cache["generated_at"]}


def _refresh_news_loop():
    while True:
        try:
            with news_lock:
                news_cache["articles"] = fetch_dashboard_articles()
                news_cache["generated_at"] = datetime.now(TIMEZONE)
                _export_news_json(news_cache["articles"], news_cache["generated_at"]) 
        except Exception:
            pass
        time.sleep(max(1, NEWS_REFRESH_INTERVAL_SECONDS))


def _refresh_quotes_loop():
    while True:
        try:
            with quotes_lock:
                quotes_cache["quotes"] = fetch_quotes()
                quotes_cache["generated_at"] = datetime.now(TIMEZONE)
                _export_quotes_json(quotes_cache["quotes"], quotes_cache["generated_at"]) 
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
            _export_news_json(news_cache["articles"], news_cache["generated_at"]) 
    except Exception:
        pass
    # Prime de cotações em segundo plano para não bloquear primeira renderização
    refresh_quotes_async_once()


def refresh_news_async_once():
    def _run():
        try:
            with news_lock:
                news_cache["articles"] = fetch_dashboard_articles()
                news_cache["generated_at"] = datetime.now(TIMEZONE)
                _export_news_json(news_cache["articles"], news_cache["generated_at"]) 
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def refresh_quotes_async_once():
    def _run():
        try:
            with quotes_lock:
                quotes_cache["quotes"] = fetch_quotes()
                quotes_cache["generated_at"] = datetime.now(TIMEZONE)
                _export_quotes_json(quotes_cache["quotes"], quotes_cache["generated_at"]) 
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
    payload = get_cached_quotes()
    quotes: List[Quote] = payload["quotes"]
    return jsonify({
        "generated_at": (payload["generated_at"] or datetime.now(TIMEZONE)).isoformat(),
        "quotes": [serialize_quote(q) for q in quotes],
    })




prime_cache_on_startup()
start_background_refreshers()

if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=5000, debug=True)
