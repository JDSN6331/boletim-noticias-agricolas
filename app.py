from datetime import datetime, timedelta
from typing import Dict, List

from flask import Flask, jsonify, render_template, request, url_for

from config import TIMEZONE
from scraper import Article, TOPIC_CONFIG, fetch_dashboard_articles, Quote, fetch_quotes

app = Flask(__name__)

CACHE_TTL_MINUTES = 15
QUOTES_CACHE_TTL_MINUTES = 15
news_cache: Dict[str, object] = {"articles": [], "generated_at": None}
quotes_cache: Dict[str, object] = {"quotes": [], "generated_at": None}


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
    generated_at = news_cache["generated_at"]
    needs_refresh = (
        force_refresh
        or not news_cache["articles"]
        or not generated_at
        or (now - generated_at) > timedelta(minutes=CACHE_TTL_MINUTES)
        # Se o cache antigo não possui o campo 'source', force refresh
        or (
            isinstance(news_cache.get("articles"), list)
            and any(not hasattr(a, "source") for a in news_cache.get("articles", []))
        )
    )

    if needs_refresh:
        articles = fetch_dashboard_articles()
        news_cache["articles"] = articles
        news_cache["generated_at"] = now

    return {"articles": news_cache["articles"], "generated_at": news_cache["generated_at"]}


def get_cached_quotes(force_refresh: bool = False) -> Dict[str, object]:
    now = datetime.now(TIMEZONE)
    generated_at = quotes_cache["generated_at"]
    needs_refresh = (
        force_refresh
        or not quotes_cache["quotes"]
        or not generated_at
        or (now - generated_at) > timedelta(minutes=QUOTES_CACHE_TTL_MINUTES)
    )
    if needs_refresh:
        quotes_cache["quotes"] = fetch_quotes()
        quotes_cache["generated_at"] = now
    return {"quotes": quotes_cache["quotes"], "generated_at": quotes_cache["generated_at"]}


@app.route("/")
def index():
    payload = get_cached_articles()
    qpayload = get_cached_quotes()
    articles = payload["articles"]

    # Garante que o número de artigos seja múltiplo de 3
    num_articles = len(articles)
    if num_articles > 0:
        num_articles_to_show = (num_articles // 3) * 3
        articles = articles[:num_articles_to_show]

    serialized_articles = [serialize_article(article) for article in articles]
    serialized_quotes = [serialize_quote(q) for q in qpayload["quotes"]]
    return render_template(
        "index.html", initial_articles=serialized_articles, initial_quotes=serialized_quotes, generated_at=payload["generated_at"]
    )


@app.route("/api/news", methods=["GET"])
def api_news():
    payload = get_cached_articles(force_refresh=request.args.get("refresh") == "true")
    articles: List[Article] = payload["articles"]

    # Garante que o número de artigos seja múltiplo de 3
    num_articles = len(articles)
    if num_articles > 0:
        num_articles_to_show = (num_articles // 3) * 3
        articles = articles[:num_articles_to_show]

    return jsonify(
        {
            "generated_at": (payload["generated_at"] or datetime.now(TIMEZONE)).isoformat(),
            "articles": [serialize_article(article) for article in articles],
        }
    )


@app.route("/api/quotes", methods=["GET"])
def api_quotes():
    payload = get_cached_quotes(force_refresh=request.args.get("refresh") == "true")
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


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=5000, debug=True)
