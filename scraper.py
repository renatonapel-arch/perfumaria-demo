"""Scraper Fragrantica via Playwright headless.

Site bloqueia curl/requests (403). Playwright com chromium real passa.
Extrai marca, modelo, ano, concentração, família, notas topo/coração/fundo,
nota, votos, foto — a partir da URL da página do perfume.

Uso:
    from scraper import scrape_fragrantica
    data = scrape_fragrantica("https://www.fragrantica.com.br/perfume/...")
    # → dict com todos os campos ou raises ScrapeError

Padrão do howto do Renato: preview_start + get_page_text.
Aqui em Python: sync_playwright + page.content() + BeautifulSoup.
"""
from __future__ import annotations
import re, json
from typing import Optional
from playwright.sync_api import sync_playwright, Error as PWError
from bs4 import BeautifulSoup

# fam olfativa da Fragrantica → key interna do app
FAMILY_MAP = {
    'leather': 'leather', 'couro': 'leather', 'leathery': 'leather',
    'oriental': 'oriental', 'amber': 'oriental', 'âmbar': 'oriental', 'ambery': 'oriental',
    'fresh': 'fresh', 'citrus': 'fresh', 'cítrico': 'fresh', 'aromatic': 'fresh',
    'woody': 'woody', 'amadeirado': 'woody',
    'floral': 'floral',
    'gourmand': 'gourmand', 'sweet': 'gourmand', 'doce': 'gourmand',
    'chypre': 'chypre', 'chipre': 'chypre',
    'aquatic': 'aquatic', 'aquático': 'aquatic', 'marine': 'aquatic',
    'tobacco': 'tobacco', 'tabaco': 'tobacco',
}
CONCENTRACOES = ['Elixir', 'Parfum', 'EDP', 'EDT', 'EDC']

# concentração explícita no nome tem prioridade sobre padrão
CONCENTRACOES_FULL = {
    'eau de parfum': 'EDP',
    'eau de toilette': 'EDT',
    'eau de cologne': 'EDC',
    'parfum': 'Parfum',
    'elixir': 'Elixir',
    'extrait': 'Parfum',
}


class ScrapeError(Exception):
    pass


def _guess_family(txt: str) -> str:
    if not txt:
        return 'oriental'
    t = txt.lower()
    # ordem importa — mais específico primeiro
    for key in ('leather', 'couro', 'tobacco', 'tabaco', 'aquatic', 'aquático', 'marine',
                'gourmand', 'chypre', 'chipre', 'floral', 'woody', 'amadeirado',
                'oriental', 'amber', 'âmbar', 'fresh', 'citrus', 'cítrico'):
        if key in t:
            return FAMILY_MAP.get(key, 'oriental')
    return 'oriental'


def _guess_concentracao(nome: str) -> str:
    n = (nome or '').lower()
    for full, short in CONCENTRACOES_FULL.items():
        if full in n:
            return short
    for c in CONCENTRACOES:
        if c.lower() in n:
            return c
    return 'EDT'


def _find_prop(soup, prop):
    el = soup.find(attrs={'itemprop': prop})
    if not el:
        return None
    return el.get('content') or el.get_text(strip=True) or None


def _parse_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, 'lxml')

    # ---- foto (og:image) ----
    foto = None
    og = soup.find('meta', property='og:image')
    if og: foto = og.get('content')

    # ---- og:description e og:title (usados como fallback + regex de ano/família) ----
    og_desc = ''
    e = soup.find('meta', property='og:description')
    if e: og_desc = e.get('content','')
    og_title = ''
    e = soup.find('meta', property='og:title')
    if e: og_title = e.get('content','')

    # ---- marca: itemprop=brand contém <a>Marca</a> ----
    marca = None
    brand_el = soup.find(itemprop='brand')
    if brand_el:
        a = brand_el.find('a')
        marca = (a.get_text(strip=True) if a else brand_el.get_text(strip=True)) or None

    # ---- modelo: itemprop=name é "<Nome><Marca><Gênero>" grudado; melhor tirar da URL ou description ----
    modelo = None
    # tenta URL: /perfume/<Brand>/<Modelo-slug>-<id>.html
    m = re.search(r'/perfume/[^/]+/([^/]+?)-\d+\.html', url)
    if m:
        modelo = m.group(1).replace('-', ' ').strip()
    if not modelo and og_title:
        # og_title: "Aventus Creed Colônia - a fragrância Masculino 2010"
        # pega a parte antes da marca
        if marca:
            base = og_title.split(' - ')[0]  # "Aventus Creed Colônia"
            # remove marca e concentração pra ficar só o modelo
            base = re.sub(re.escape(marca), '', base, flags=re.I)
            base = re.sub(r'\b(Colônia|Eau de Toilette|Eau de Parfum|Cologne|Parfum|Elixir|Eau)\b', '', base, flags=re.I)
            modelo = base.strip() or None

    # fallback: se ainda nada, usa itemprop=name limpando o gênero grudado
    if not modelo:
        raw_name = _find_prop(soup, 'name')
        if raw_name:
            n = re.sub(r'(Masculino|Feminino|Unissex)$', '', raw_name).strip()
            if marca:
                n = re.sub(re.escape(marca)+r'$', '', n).strip()
            modelo = n or None

    # ---- ano: og_description ou HTML ----
    ano = None
    m = re.search(r'lançado?\s+em\s+(\d{4})', og_desc, re.I)
    if not m:
        m = re.search(r'launched\s+in\s+(\d{4})', og_desc, re.I)
    if not m:
        m = re.search(r'\b(19[7-9]\d|20[0-4]\d)\b', og_desc)
    if not m:
        m = re.search(r'\b(19[7-9]\d|20[0-4]\d)\b', og_title)
    if m:
        try: ano = int(m.group(1))
        except ValueError: pass

    # ---- notas olfativas: extrai da div#pyramid ----
    notas_topo = notas_coracao = notas_fundo = None
    pyramid = soup.select_one('#pyramid')
    if pyramid:
        # coleta todos os <a href="/notas/..."> na ordem que aparecem
        note_links = pyramid.select('a[href*="/notas/"]')
        notes_seq = [a.get_text(strip=True) for a in note_links if a.get_text(strip=True)]
        # descobre em qual índice começa cada seção pelo texto do pyramid
        txt = pyramid.get_text(separator='|')
        # posições relativas das labels
        idx_topo = re.search(r'Notas de Topo|Top Notes|Notas de Saída', txt)
        idx_cor  = re.search(r'Notas de Coração|Middle Notes|Heart Notes', txt)
        idx_base = re.search(r'Notas de Fundo|Notas de Base|Base Notes', txt)
        # separa os names pelo pyramid text: quebra por marcador e checa quais aparecem em cada seção
        pos_topo = idx_topo.start() if idx_topo else -1
        pos_cor  = idx_cor.start() if idx_cor else -1
        pos_base = idx_base.start() if idx_base else -1
        buckets = {'topo': [], 'coracao': [], 'fundo': []}
        for name in notes_seq:
            p = txt.find(name)
            if p < 0: continue
            if pos_base != -1 and p > pos_base: buckets['fundo'].append(name)
            elif pos_cor != -1 and p > pos_cor: buckets['coracao'].append(name)
            elif pos_topo != -1 and p > pos_topo: buckets['topo'].append(name)
        def _fmt(lst):
            uniq = list(dict.fromkeys(lst))[:10]
            return ', '.join(uniq) if uniq else None
        notas_topo = _fmt(buckets['topo'])
        notas_coracao = _fmt(buckets['coracao'])
        notas_fundo = _fmt(buckets['fundo'])

    # ---- rating + votes ----
    nota_fragrantica = None
    votos_fragrantica = None
    rv = soup.find(itemprop='ratingValue')
    if rv:
        try:
            nota_fragrantica = float((rv.get('content') or rv.get_text(strip=True)).replace(',', '.'))
        except (ValueError, AttributeError): pass
    rc = soup.find(itemprop='ratingCount')
    if rc:
        try:
            votos_fragrantica = int(re.sub(r'\D', '', rc.get('content') or rc.get_text(strip=True)) or 0)
        except (ValueError, AttributeError): pass

    # ---- concentração — só olha no modelo (og_title tem "Colônia" que confunde) ----
    concentracao = _guess_concentracao(modelo or '')

    # ---- família olfativa (accord Fragrantica) ----
    accord_txt = ''
    # tenta pelo accord-bar (barras coloridas de famílias)
    for el in soup.select('[class*="accord-bar"]')[:3]:
        accord_txt += ' ' + el.get_text(strip=True)
    # og_desc costuma ter "é um perfume <Família> Masculino"
    familia = _guess_family(accord_txt + ' ' + og_desc)

    return {
        'marca': marca,
        'modelo': modelo,
        'ano': ano,
        'concentracao': concentracao,
        'familia': familia,
        'notas_topo': notas_topo,
        'notas_coracao': notas_coracao,
        'notas_fundo': notas_fundo,
        'nota_fragrantica': nota_fragrantica,
        'votos_fragrantica': votos_fragrantica,
        'foto': foto,
    }


UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')


def scrape_fragrantica(url: str, timeout_ms: int = 30_000) -> dict:
    """Abre a página no chromium headless e devolve dict com campos preenchidos."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )
            ctx = browser.new_context(
                user_agent=UA,
                locale='pt-BR',
                extra_http_headers={'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'},
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            # deixa o JS rodar um pouco pra revelar pyramid/rating
            try:
                page.wait_for_selector('span[itemprop="ratingValue"], meta[property="og:image"]', timeout=8000)
            except PWError:
                pass
            page.wait_for_timeout(1200)
            html = page.content()
            browser.close()
    except PWError as e:
        raise ScrapeError(f'Playwright falhou: {e}')

    parsed = _parse_html(html, url)
    # se marca e modelo vazios, provavelmente Cloudflare bloqueou
    if not parsed.get('marca') or not parsed.get('modelo'):
        raise ScrapeError('Não consegui extrair marca/modelo — página bloqueada ou layout mudou')

    # remove campos None pra não sobrescrever com None no frontend
    return {k: v for k, v in parsed.items() if v is not None and v != ''}


if __name__ == '__main__':
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.fragrantica.com.br/perfume/Creed/Aventus-9828.html'
    print(json.dumps(scrape_fragrantica(url), ensure_ascii=False, indent=2))
