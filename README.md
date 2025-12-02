# Boletim Informativo Agrícola

Aplicação web em Flask que monta um painel com as principais notícias agrícolas dos últimos 7 dias, agrupando por temas e com layout responsivo. Inclui uma API para atualização dos dados.

## Funcionalidades
- Coleta de notícias dos últimos **7 dias** por tema.
- Tópicos monitorados: Defensivos Agrícolas, Fertilizantes de Solo, Irrigação, Soja, Milho e Café.
- Cache de resultados por **15 minutos** para reduzir chamadas.
- Interface responsiva com cards e cores por tema.

## Stack
- Backend: `Flask`, `requests`, `beautifulsoup4`, `lxml`.
- Frontend: HTML + CSS + JS (vanilla).

## Requisitos
- Python 3.10+
- Pacotes do `requirements.txt`:
  - Flask, requests, beautifulsoup4, lxml, python-dateutil
  - Opcional: `tzdata` (se o Windows não tiver base de fusos horários)

## Instalação
1. Crie e ative um ambiente Python.
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   # opcional em Windows, caso veja erro de timezone
   pip install tzdata
   ```

## Executando
```bash
python app.py
```
Abra `http://127.0.0.1:5000` no navegador.

## Configuração
- Fuso horário: `config.py` define `TIMEZONE` (por padrão `America/Sao_Paulo`).
- Janela temporal de coleta: `scraper.py` → `LEAD_TIME_DAYS = 7`.
- Cache de notícias: `app.py` → `CACHE_TTL_MINUTES = 15`.

## Endpoints
- `GET /` — Renderiza o dashboard.
- `GET /api/news` — Retorna as notícias atuais (respeitando o cache). Use `?refresh=true` para forçar atualização.

## Como mudar os temas ou cores
- Arquivo: `scraper.py`
- Mapa `TOPIC_CONFIG` contém cada tema com:
  - `label` (rótulo), `slug` (categoria do site), `keywords` (palavras‑chave), `color` (hex)
  - Exemplo de slugs usados: `agronegocio`, `soja`, `milho`, `cafe`.

## Fontes de notícias
- Site base: `https://www.noticiasagricolas.com.br`
- Listagens por tema: `https://www.noticiasagricolas.com.br/noticias/<slug>/`
  - Slugs utilizados: `agronegocio` (Defensivos/Fertilizantes/Irrigação), `soja`, `milho`, `cafe`.
- Páginas de matéria individuais são acessadas a partir dos links das listagens.


## Observações
- Alguns avisos do editor sobre `<script>` em `index.html` são esperados, pois o template Jinja injeta dados do backend e só se tornam JS válido depois da renderização.

## Licença
Uso interno. As notícias e marcas pertencem aos seus respectivos titulares. Fonte de dados: Notícias Agrícolas.
