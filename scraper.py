import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.noticiasagricolas.com.br"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0 Safari/537.36"
    ),
}
LEAD_TIME_DAYS = 7


@dataclass
class Article:
    topic_key: str
    topic_label: str
    title: str
    summary: str
    url: str
    image_url: str
    published_at: datetime
    source: str

    @property
    def iso_published_at(self) -> str:
        return self.published_at.isoformat()


TOPIC_CONFIG: Dict[str, Dict[str, object]] = {
    "defensivos": {
        "label": "Defensivos",
        "slug": "agronegocio",
        "keywords": [
            "defensiv",
            "biológico",
            "praga",
            "fungicida",
            "inseticida",
            "herbicida",
        ],
        "color": "#0FA66D",
    },
    "fertilizantes": {
        "label": "Fertilizantes",
        "slug": "agronegocio",
        "keywords": [
            "fertiliz",
            "adubo",
            "nutri",
            "solo",
            "fertirrig",
            "nutriente",
        ],
        "color": "#77C043",
    },
    "irrigacao": {
        "label": "Irrigação",
        "slug": "agronegocio",
        "keywords": [
            "irrig",
            "gotejamento",
            "pivô central",
            "pivo central",
            "aspersão",
            "aspersao",
        ],
        "color": "#1E90FF",
    },
    "soja": {
        "label": "Soja",
        "slug": "soja",
        "keywords": [],
        "color": "#23A455",
    },
    "milho": {
        "label": "Milho",
        "slug": "milho",
        "keywords": [],
        "color": "#E6B325",
    },
    "cafe": {
        "label": "Café",
        "slug": "cafe",
        "keywords": [],
        "color": "#8B4513",
    },
}

# Funções auxiliares de relevância e exclusões
def _collect_global_keywords() -> List[str]:
    tokens: List[str] = []
    for key, cfg in TOPIC_CONFIG.items():
        tokens.append(key.lower())
        for kw in cfg.get("keywords", []):  # type: ignore[index]
            tokens.append(str(kw).lower())
    tokens.extend(["cafe", "café", "irrigacao", "irrigação"])
    return list({t for t in tokens if t})

GLOBAL_KEYWORDS = _collect_global_keywords()

def is_relevant_article_text(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(tok in text for tok in GLOBAL_KEYWORDS)

def is_disallowed_agrolink(url: str, title: str = "") -> bool:
    u = (url or "").lower()
    t = (title or "").lower()
    bad = [
        "previsao", "previsão", "tempo", "clima", "meteorolog",
        "cotacao", "cotacoes", "cotações",
        "podcast", "video", "vídeo", "galeria", "classificado", "classificados",
    ]
    return any(b in u or b in t for b in bad)

DATE_HEADING_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")
DATE_TIME_PATTERN = re.compile(r"(\d{2}/\d{2}/\d{4}).*?(\d{2}:\d{2})")


class NoticiasAgricolasScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.lead_time = timedelta(days=LEAD_TIME_DAYS)

    def collect_dashboard_articles(
        self, topic_sequence: Optional[List[str]] = None, limit: int = 15
    ) -> List[Article]:
        if topic_sequence is None:
            topic_sequence = ["defensivos", "fertilizantes", "irrigacao", "soja", "milho", "cafe"]

        articles: List[Article] = []

        def extend_with_topic(topic: str, take: int) -> None:
            nonlocal articles
            for article in self._fetch_topic_articles(topic, max_results=take):
                if any(existing.url == article.url for existing in articles):
                    continue
                articles.append(article)
                if len(articles) >= limit:
                    return

        # Passo 1: garantir ao menos um item por tema
        for topic in topic_sequence:
            if len(articles) >= limit:
                break
            extend_with_topic(topic, take=1)

        # Passo 2: completar o grid com notícias extras mantendo os temas
        if len(articles) < limit:
            for topic in topic_sequence:
                if len(articles) >= limit:
                    break
                extend_with_topic(topic, take=3)

        return articles[:limit]

    def _fetch_topic_articles(self, topic_key: str, max_results: int = 1) -> List[Article]:
        if topic_key not in TOPIC_CONFIG:
            raise ValueError(f"Topic '{topic_key}' is not configured.")

        cfg = TOPIC_CONFIG[topic_key]
        listing = self._parse_listing(cfg["slug"], max_candidates=30)
        collected: List[Article] = []

        for item in listing:
            if datetime.utcnow() - item["listed_at"] > self.lead_time:
                continue

            article = self._build_article(topic_key, item["url"])
            if not article:
                continue

            if datetime.utcnow() - article.published_at > self.lead_time:
                continue

            if not self._matches_topic(article, cfg):
                continue

            collected.append(article)
            if len(collected) >= max_results:
                break

        return collected

    def _parse_listing(self, slug: str, max_candidates: int = 20) -> List[Dict[str, object]]:
        url = f"{BASE_URL}/noticias/{slug}/"
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        candidates: List[Dict[str, object]] = []

        for heading in soup.select("#content h3"):
            heading_text = heading.get_text(strip=True)
            if not DATE_HEADING_PATTERN.fullmatch(heading_text):
                continue

            ul = heading.find_next_sibling("ul")
            if not ul:
                continue

            for li in ul.select("li.horizontal"):
                anchor = li.find("a", href=True)
                title_el = li.find("h2")
                time_el = li.find(class_="hora")

                if not anchor or not title_el:
                    continue

                published_at = self._combine_date_time(heading_text, time_el)

                candidates.append(
                    {
                        "url": urljoin(BASE_URL, anchor["href"]),
                        "title": title_el.get_text(strip=True),
                        "listed_at": published_at,
                    }
                )

                if len(candidates) >= max_candidates:
                    return candidates

        return candidates

    def _combine_date_time(self, date_text: str, time_element) -> datetime:
        if time_element:
            time_text = time_element.get_text(strip=True)
            try:
                return datetime.strptime(f"{date_text} {time_text}", "%d/%m/%Y %H:%M")
            except ValueError:
                pass
        return datetime.strptime(date_text, "%d/%m/%Y")

    def _build_article(self, topic_key: str, article_url: str) -> Optional[Article]:
        response = self.session.get(article_url, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        hero_image = self._extract_image(soup)
        if not hero_image:
            return None

        title_el = soup.find("h1") or soup.find("h2") or soup.title
        if not title_el:
            return None

        summary = self._extract_summary(soup)
        if not summary:
            return None

        published_at = self._extract_datetime(soup)
        if not published_at:
            published_at = datetime.utcnow()

        cfg = TOPIC_CONFIG[topic_key]
        return Article(
            topic_key=topic_key,
            topic_label=cfg["label"],
            title=self._sanitize_text(title_el.get_text(strip=True)),
            summary=self._sanitize_text(summary),
            url=article_url,
            image_url=hero_image,
            published_at=published_at,
            source="Notícias Agrícolas",
        )

    def _extract_image(self, soup: BeautifulSoup) -> Optional[str]:
        meta_img = soup.find("meta", property="og:image")
        if meta_img and meta_img.get("content"):
            return meta_img["content"]
        figure_img = soup.select_one(".materia img")
        if figure_img and figure_img.get("src"):
            return urljoin(BASE_URL, figure_img["src"])
        return None

    def _extract_summary(self, soup: BeautifulSoup) -> Optional[str]:
        body = soup.select_one(".materia") or soup.select_one(".conteudo") or soup.select_one(".news-body")
        if not body:
            return None
        paragraphs = [
            p.get_text(" ", strip=True)
            for p in body.find_all("p")
            if p.get_text(strip=True)
            and "Logotipo Notícias Agrícolas" not in p.get_text()
            and len(p.get_text(strip=True)) > 25
        ]
        for paragraph in paragraphs[:5]:
            clean = self._sanitize_text(paragraph)
            if len(clean) > 50:
                return clean
        return paragraphs[0] if paragraphs else None

    def _extract_datetime(self, soup: BeautifulSoup) -> Optional[datetime]:
        block = soup.select_one(".datas") or soup.select_one(".meta")
        if not block:
            return None
        text = block.get_text(" ", strip=True)
        match = DATE_TIME_PATTERN.search(text)
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%d/%m/%Y %H:%M")
            except ValueError:
                return None
        date_match = DATE_HEADING_PATTERN.search(text)
        if date_match:
            return datetime.strptime(date_match.group(0), "%d/%m/%Y")
        return None

    def _matches_topic(self, article: Article, cfg: Dict[str, object]) -> bool:
        keywords: List[str] = cfg.get("keywords", [])  # type: ignore[assignment]
        if not keywords:
            return True
        haystack = f"{article.title} {article.summary}".lower()
        return any(keyword.lower() in haystack for keyword in keywords)

    def _sanitize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


def fetch_dashboard_articles() -> List[Article]:
    """Busca e combina artigos das fontes disponíveis, intercalando e removendo duplicados."""
    na = NoticiasAgricolasScraper()
    na_items = na.collect_dashboard_articles(limit=15)

    try:
        gcp = GlobalCropProtectionScraper()
        gcp_items = gcp.collect_recent_articles(limit=15)
    except Exception:
        gcp_items = []

    try:
        ag = AgrolinkScraper()
        ag_items = ag.collect_recent_articles(limit=15)
    except Exception:
        ag_items = []

    combined: List[Article] = []
    i_na = i_gcp = i_ag = 0
    # Round-robin NA -> GCP -> AG, até 15
    while len(combined) < 15 and (
        i_na < len(na_items) or i_gcp < len(gcp_items) or i_ag < len(ag_items)
    ):
        if i_na < len(na_items):
            a = na_items[i_na]
            if not any(x.url == a.url for x in combined):
                combined.append(a)
            i_na += 1
        if len(combined) >= 15:
            break
        if i_gcp < len(gcp_items):
            b = gcp_items[i_gcp]
            if not any(x.url == b.url for x in combined):
                combined.append(b)
            i_gcp += 1
        if len(combined) >= 15:
            break
        if i_ag < len(ag_items):
            c = ag_items[i_ag]
            if not any(x.url == c.url for x in combined):
                combined.append(c)
            i_ag += 1

    return combined


class GlobalCropProtectionScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.lead_time = timedelta(days=LEAD_TIME_DAYS)

    def _to_naive_utc(self, dt: datetime) -> datetime:
        try:
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
        return dt

    def collect_recent_articles(self, limit: int = 15) -> List[Article]:
        # Prioriza RSS por ser mais estável e menos sujeito a bloqueios
        rss_items = self._fetch_rss_items(max_items=60)
        collected: List[Article] = []
        for item in rss_items:
            if datetime.utcnow() - item["published_at"] > self.lead_time:
                continue
            art = self._article_from_rss(item)
            if not art:
                continue
            if not art.image_url:
                continue
            if not is_relevant_article_text(art.title, art.summary):
                continue
            collected.append(art)
            if len(collected) >= limit:
                return collected

        # Fallback para parsing de páginas se RSS falhar ou for insuficiente
        listing = self._parse_listing(max_candidates=40)
        for item in listing:
            if datetime.utcnow() - item["listed_at"] > self.lead_time:
                continue
            article = self._build_article(item["url"])  
            if not article:
                continue
            if not article.image_url:
                continue
            if not is_relevant_article_text(article.title, article.summary):
                continue
            if datetime.utcnow() - article.published_at > self.lead_time:
                continue
            collected.append(article)
            if len(collected) >= limit:
                break
        return collected

    def _fetch_rss_items(self, max_items: int = 50) -> List[Dict[str, object]]:
        urls = [
            "https://globalcropprotection.com/feed/",
            "https://globalcropprotection.com/category/news/feed/",
        ]
        items: List[Dict[str, object]] = []
        for url in urls:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200:
                    continue
            except Exception:
                continue
            soup = BeautifulSoup(resp.text, "xml")
            for item in soup.find_all("item"):
                try:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")
                    pub_el = item.find("pubDate") or item.find("dc:date")
                    encl = item.find("enclosure")
                    media = item.find("media:content")
                    title = title_el.get_text(strip=True) if title_el else ""
                    link = link_el.get_text(strip=True) if link_el else ""
                    desc = desc_el.get_text(strip=True) if desc_el else ""
                    img = ""
                    if encl and encl.get("url"):
                        img = encl.get("url")
                    elif media and media.get("url"):
                        img = media.get("url")
                    published_at = datetime.utcnow()
                    if pub_el and pub_el.get_text(strip=True):
                        dt_txt = pub_el.get_text(strip=True)
                        for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]:
                            try:
                                published_at = datetime.strptime(dt_txt.replace("Z", "+0000"), fmt)
                                break
                            except Exception:
                                pass
                    published_at = self._to_naive_utc(published_at)
                    if not link:
                        continue
                    items.append({
                        "title": title,
                        "link": link,
                        "summary": desc,
                        "image_url": img,
                        "published_at": published_at,
                    })
                    if len(items) >= max_items:
                        return items
                except Exception:
                    continue
        return items

    def _article_from_rss(self, item: Dict[str, object]) -> Optional[Article]:
        title = str(item.get("title", ""))
        summary = str(item.get("summary", ""))
        url = str(item.get("link", ""))
        image_url = str(item.get("image_url", ""))
        published_at = item.get("published_at") or datetime.utcnow()
        if isinstance(published_at, datetime):
            published_at = self._to_naive_utc(published_at)
        # Se não houver imagem no RSS, tenta obter do artigo
        if not image_url:
            try:
                page = self.session.get(url, timeout=12)
                if page.status_code == 200:
                    psoup = BeautifulSoup(page.text, "lxml")
                    og = psoup.find("meta", property="og:image")
                    if og and og.get("content"):
                        image_url = og.get("content")
            except Exception:
                pass
        if not image_url:
            return None
        text = f"{title} {summary}".lower()
        topic_key = "defensivos"
        if any(k in text for k in ["fertiliz", "fertilizer", "nutri", "nutrição", "nutrient", "nue", "foliar"]):
            topic_key = "fertilizantes"
        elif any(k in text for k in ["irrig", "irrigation"]):
            topic_key = "irrigacao"
        elif any(k in text for k in ["soy", "soja"]):
            topic_key = "soja"
        elif any(k in text for k in ["corn", "milho"]):
            topic_key = "milho"
        elif any(k in text for k in ["coffee", "café", "cafe"]):
            topic_key = "cafe"
        cfg = TOPIC_CONFIG[topic_key]
        return Article(
            topic_key=topic_key,
            topic_label=cfg["label"],
            title=NoticiasAgricolasScraper._sanitize_text(self, title),
            summary=NoticiasAgricolasScraper._sanitize_text(self, summary or title),
            url=url,
            image_url=image_url or "",
            published_at=published_at if isinstance(published_at, datetime) else datetime.utcnow(),
            source="Global Crop Protection",
        )

    def _parse_listing(self, max_candidates: int = 30) -> List[Dict[str, object]]:
        urls = ["https://globalcropprotection.com/news/", "https://globalcropprotection.com/"]
        candidates: List[Dict[str, object]] = []
        for url in urls:
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
            except Exception:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            anchors = []
            anchors.extend(soup.select("article a[href]"))
            anchors.extend(soup.select(".post a[href]"))
            anchors.extend(soup.select("h2 a[href]"))
            anchors.extend(soup.select("h3 a[href]"))
            seen = set()
            for a in anchors:
                href = a.get("href")
                if not href:
                    continue
                full = href if href.startswith("http") else urljoin(url, href)
                if "globalcropprotection.com" not in full:
                    continue
                low = full.lower()
                if any(x in low for x in ["/author/", "/tag/", "/category/", "/page/"]):
                    continue
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(strip=True)
                if not title:
                    continue
                candidates.append({
                    "url": full,
                    "title": title,
                    "listed_at": datetime.utcnow(),
                })
                if len(candidates) >= max_candidates:
                    return candidates
        return candidates

    def _build_article(self, url: str) -> Optional[Article]:
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None
        except Exception:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.find("h1") or soup.find("h2") or soup.title
        if not title_el:
            return None
        og_img = soup.find("meta", property="og:image")
        hero_image = og_img.get("content") if og_img and og_img.get("content") else ""
        if not hero_image:
            img_el = soup.select_one("article img") or soup.find("img")
            hero_image = img_el.get("src") if img_el and img_el.get("src") else ""
        if not hero_image:
            return None
        body = soup.select_one("article") or soup.select_one("main") or soup
        paragraphs = [p.get_text(" ", strip=True) for p in body.find_all("p") if p.get_text(strip=True)]
        summary = None
        for paragraph in paragraphs[:5]:
            if len(paragraph) > 40:
                summary = paragraph
                break
        if not summary:
            summary = paragraphs[0] if paragraphs else title_el.get_text(strip=True)
        # Data de publicação: tenta meta ISO, senão extrai do texto (dd/MM/yyyy)
        published_at = None
        meta_pub = soup.find("meta", property="article:published_time") or soup.find("time")
        if meta_pub:
            dt = meta_pub.get("content") or meta_pub.get("datetime") or meta_pub.get_text(strip=True)
            try:
                if dt:
                    published_at = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            except Exception:
                published_at = None
        if published_at is None:
            full_text = soup.get_text(" ", strip=True)
            m = DATE_TIME_PATTERN.search(full_text) or DATE_HEADING_PATTERN.search(full_text)
            if m:
                date_str = m.group(1) if m.groups() else m.group(0)
                try:
                    d, mth, y = map(int, date_str.split("/"))
                    published_at = datetime(y, mth, d)
                except Exception:
                    published_at = None
        if published_at is None:
            # Fallback para garantir valor; não será exibido horário no UI
            # Se não achou data, assume que é muito antigo para evitar lixo
            return None
        published_at = self._to_naive_utc(published_at)
        text = f"{title_el.get_text(strip=True)} {summary}".lower()
        topic_key = "defensivos"
        if any(k in text for k in ["fertiliz", "fertilizer", "nutri", "nutrição", "nutrient", "nue", "foliar"]):
            topic_key = "fertilizantes"
        elif any(k in text for k in ["irrig", "irrigation"]):
            topic_key = "irrigacao"
        elif any(k in text for k in ["soy", "soja"]):
            topic_key = "soja"
        elif any(k in text for k in ["corn", "milho"]):
            topic_key = "milho"
        elif any(k in text for k in ["coffee", "café", "cafe"]):
            topic_key = "cafe"
        cfg = TOPIC_CONFIG[topic_key]
        return Article(
            topic_key=topic_key,
            topic_label=cfg["label"],
            title=NoticiasAgricolasScraper._sanitize_text(self, title_el.get_text(strip=True)),
            summary=NoticiasAgricolasScraper._sanitize_text(self, summary),
            url=url,
            image_url=hero_image,
            published_at=published_at,
            source="Global Crop Protection",
        )


class AgrolinkScraper:
    BASES = [
        "https://www.agrolink.com.br/",
        "https://www.agrolink.com.br/noticias/",
    ]

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.lead_time = timedelta(days=LEAD_TIME_DAYS)

    def collect_recent_articles(self, limit: int = 15) -> List[Article]:
        listing = self._parse_listing(max_candidates=60)
        collected: List[Article] = []
        for item in listing:
            if datetime.utcnow() - item["listed_at"] > self.lead_time:
                continue
            article = self._build_article(item["url"])  
            if not article:
                continue
            if not article.image_url:
                continue
            if not is_relevant_article_text(article.title, article.summary):
                continue
            if datetime.utcnow() - article.published_at > self.lead_time:
                continue
            collected.append(article)
            if len(collected) >= limit:
                break
        return collected

    def _parse_listing(self, max_candidates: int = 50) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        seen = set()
        for base in self.BASES:
            try:
                resp = self.session.get(base, timeout=15)
                resp.raise_for_status()
            except Exception:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a[href]"):
                href = a.get("href")
                if not href:
                    continue
                full = href if href.startswith("http") else urljoin(base, href)
                if "agrolink.com.br" not in full:
                    continue
                if not any(p in full for p in ["/noticia", "/noticias/"]):
                    continue
                if full in seen:
                    continue
                title = a.get_text(strip=True)
                if is_disallowed_agrolink(full, title):
                    continue
                seen.add(full)
                if not title:
                    title = full.rsplit("/", 1)[-1].replace("-", " ")
                candidates.append({
                    "url": full,
                    "title": title,
                    "listed_at": datetime.utcnow(),
                })
                if len(candidates) >= max_candidates:
                    return candidates
        return candidates

    def _build_article(self, url: str) -> Optional[Article]:
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None
        except Exception:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.find("h1") or soup.find("h2") or soup.title
        if not title_el:
            return None
        og_img = soup.find("meta", property="og:image")
        hero_image = og_img.get("content") if og_img and og_img.get("content") else ""
        if not hero_image:
            img_el = soup.select_one("article img, .post img, .conteudo img, .content img") or soup.find("img")
            if img_el:
                hero_image = (
                    img_el.get("src")
                    or img_el.get("data-src")
                    or img_el.get("data-original")
                    or img_el.get("data-lazy-src")
                    or ""
                )
        if not hero_image:
            return None
        body = soup.select_one(".content") or soup.select_one(".conteudo") or soup.select_one(".materia") or soup.select_one("article") or soup.select_one("main") or soup
        paragraphs = [p.get_text(" ", strip=True) for p in body.find_all("p") if p.get_text(strip=True)]
        summary = None
        for paragraph in paragraphs[:8]:
            if len(paragraph) > 40:
                summary = paragraph
                break
        if not summary:
            summary = paragraphs[0] if paragraphs else title_el.get_text(strip=True)
        published_at = None
        meta_pub = soup.find("meta", property="article:published_time") or soup.find("time")
        try:
            if meta_pub:
                dt = meta_pub.get("content") or meta_pub.get("datetime") or meta_pub.get_text(strip=True)
                if dt:
                    published_at = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            published_at = None
        if published_at is None:
            full_text = soup.get_text(" ", strip=True)
            m = DATE_TIME_PATTERN.search(full_text) or DATE_HEADING_PATTERN.search(full_text)
            if m:
                date_str = m.group(1) if m.groups() else m.group(0)
                try:
                    d, mth, y = map(int, date_str.split("/"))
                    published_at = datetime(y, mth, d)
                except Exception:
                    published_at = None
        if published_at is None:
            published_at = datetime.utcnow()
        text = f"{title_el.get_text(strip=True)} {summary}".lower()
        topic_key = "defensivos"
        if any(k in text for k in ["fertiliz", "adubo", "fertilizer", "nutri", "nutrição", "nutrient", "nue", "foliar"]):
            topic_key = "fertilizantes"
        elif any(k in text for k in ["irrig", "irrigação", "irrigation"]):
            topic_key = "irrigacao"
        elif "soja" in text or "soy" in text:
            topic_key = "soja"
        elif "milho" in text or "corn" in text:
            topic_key = "milho"
        elif "café" in text or "cafe" in text or "coffee" in text:
            topic_key = "cafe"
        cfg = TOPIC_CONFIG[topic_key]
        return Article(
            topic_key=topic_key,
            topic_label=cfg["label"],
            title=NoticiasAgricolasScraper._sanitize_text(self, title_el.get_text(strip=True)),
            summary=NoticiasAgricolasScraper._sanitize_text(self, summary),
            url=url,
            image_url=hero_image,
            published_at=published_at,
            source="Agrolink",
        )
@dataclass
class Quote:
    key: str
    label: str
    value: str
    change: str
    unit: str
    source: str

def fetch_quotes() -> List[Quote]:
    session = requests.Session()
    session.headers.update(HEADERS)
    items: List[Quote] = []
    try:
        r = session.get(f"{BASE_URL}/cotacoes/", timeout=15)
        if r.status_code != 200:
            raise RuntimeError("Falha ao carregar página de cotações")
        soup = BeautifulSoup(r.text, "lxml")

        # Dólar na barra superior
        usd_val = ""
        usd_var = ""
        try:
            vels = soup.select(".box-dolar .valor")
            pels = soup.select(".box-dolar .porcentagem")
            if vels:
                usd_val = vels[0].get_text(strip=True)
            if pels:
                usd_var = pels[0].get_text(strip=True)
        except Exception:
            pass
        items.append(Quote("dolar", "Dólar", usd_val, usd_var, "R$", "Notícias Agrícolas"))

        def extract_from_heading_in(soup_obj, term: str, label: str, key: str, unit: str, source: str) -> Quote:
            h = None
            for tag in soup_obj.find_all(["h2", "h3"]):
                if term.lower() in tag.get_text(" ", strip=True).lower():
                    h = tag
                    break
            val = ""
            var = ""
            if h:
                tables = []
                cur = h
                for _ in range(4):
                    cur = cur.find_next("table") if cur else None
                    if not cur:
                        break
                    tables.append(cur)
                pick = None
                if term.lower() == "soja":
                    for t in tables:
                        tx = t.get_text(" ", strip=True).lower()
                        if "r$/sc" in tx or "preço" in tx or "preco" in tx or "praça" in tx or "praca" in tx:
                            pick = t
                            break
                tbl = pick or (tables[0] if tables else None)
                if tbl:
                    txt = tbl.get_text(" ", strip=True)
                    m_val = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}[\.,]\d{2})", txt)
                    if m_val:
                        val = m_val.group(1)
                    if not val:
                        m_val2 = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}[\.,]\d{2})", txt)
                        if m_val2:
                            val = m_val2.group(1)
                    m_var = re.search(r"([+-]?\d{1,3}(?:[\.,]\d{2})%)", txt)
                    if m_var:
                        var = m_var.group(1)
            return Quote(key, label, val, var, unit, source)

        # Café Arábica (página específica)
        try:
            rc = session.get(f"{BASE_URL}/cotacoes/cafe", timeout=15)
            if rc.status_code == 200:
                csoup = BeautifulSoup(rc.text, "lxml")
                items.append(extract_from_heading_in(csoup, "Indicador Café Arábica - Cepea/Esalq", "Café", "cafe", "R$/sc", "Cepea/Esalq"))
            else:
                items.append(extract_from_heading_in(soup, "Café", "Café", "cafe", "R$/sc", "Cepea/Esalq"))
        except Exception:
            items.append(extract_from_heading_in(soup, "Café", "Café", "cafe", "R$/sc", "Cepea/Esalq"))
        items.append(extract_from_heading_in(soup, "Indicador do Milho Esalq/B3", "Milho", "milho", "R$/sc 60 kg", "ESALQ/B3"))
        s_val_quote = extract_from_heading_in(soup, "Indicador da Soja ESALQ/B3 - Paranaguá", "Soja", "soja", "R$/sc", "ESALQ/B3 - Paranaguá")
        if not s_val_quote.value:
            try:
                rs = session.get(f"{BASE_URL}/cotacoes/soja", timeout=15)
                if rs.status_code == 200:
                    ssoup = BeautifulSoup(rs.text, "lxml")
                    s_val_quote = extract_from_heading_in(ssoup, "Indicador da Soja ESALQ/B3 - Paranaguá", "Soja", "soja", "R$/sc", "ESALQ/B3 - Paranaguá")
            except Exception:
                pass
        items.append(s_val_quote)
    except Exception:
        pass
    return items
