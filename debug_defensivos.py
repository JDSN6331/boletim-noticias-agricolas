from scraper import NoticiasAgricolasScraper
scraper = NoticiasAgricolasScraper()
listing = scraper._parse_listing('agronegocio', max_candidates=40)
keywords = [k.lower() for k in scraper.__class__.__dict__['__init__'].__globals__['TOPIC_CONFIG']['defensivos']['keywords']]
for item in listing:
    soup_article = scraper._build_article('defensivos', item['url'])
    if soup_article and any(k in (soup_article.title + ' ' + soup_article.summary).lower() for k in keywords):
        print('MATCH', soup_article.title)
