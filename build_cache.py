import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (compatible; Q4FlashcardsBuilder/1.0)'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE = {
    'Toon relaties in LiDO', 'Maak een permanente link', 'Toon wetstechnische informatie',
    'Gegevens van deze regeling', 'Vergelijk met andere versies', 'Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling', 'Selecteer een andere versie', 'Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op', 'Permalink', '...'
}

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': USER_AGENT})


def parse_line(line: str):
    line = line.strip()
    if not line.startswith('* '):
        return None

    body = line[2:].strip()
    if '→' not in body:
        return {'skip': True, 'reason': 'geen pijl'}

    ref, rest = body.split('→', 1)
    ref = ref.strip()

    match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', rest)
    if not match:
        return {'skip': True, 'reason': 'link niet parsebaar', 'reference': ref}

    desc = match.group(1).strip()
    url = match.group(2).strip()

    article_match = ARTICLE_RE.search(ref)
    if not article_match:
        return {'skip': True, 'reason': 'complete regeling of wet', 'reference': ref}

    article = article_match.group(1).strip()
    lid_match = LID_RE.search(ref)
    lid = lid_match.group(1).strip() if lid_match else None
    law = ref.split(' Artikel:')[0].strip()

    label = f"{law}, artikel {article}"
    if lid:
        label += f", lid {lid}"

    return {
        'skip': False,
        'law': law,
        'article': article,
        'lid': lid,
        'reference': ref,
        'front': desc,
        'url': url,
        'label': label,
    }


def load_source_cards():
    text = DATA_FILE.read_text(encoding='utf-8')
    cards = []
    skipped = []

    for line in text.splitlines():
        parsed = parse_line(line)
        if not parsed:
            continue
        if parsed.get('skip'):
            skipped.append((parsed.get('reference', line.strip()), parsed.get('reason', 'overgeslagen')))
            continue
        cards.append(parsed)

    return cards, skipped


def normalize_text(text: str) -> str:
    text = html.unescape(text or '').replace('\xa0', ' ')
    text = re.sub(r'\r', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_lines(strings):
    output = []
    for value in strings:
        value = normalize_text(value)
        if not value or value in NOISE:
            continue
        output.append(value)
    return output


def build_tekst_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params['tekst'] = ['1']
    query = urlencode(params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def extract_article(page_lines, article):
    start = None
    for index, line in enumerate(page_lines):
        if re.match(rf'^Artikel\s+{re.escape(article)}(?:\b|[\s.:-])', line, re.IGNORECASE):
            start = index
            break
    if start is None:
        return None

    block = [page_lines[start]]
    content_found = False

    for line in page_lines[start + 1:]:
        if re.match(r'^Artikel\s+[0-9A-Za-z:.]+(?:\b|[\s.:-])', line, re.IGNORECASE):
            break
        block.append(line)
        if not re.match(r'^(Artikel|Lid)\b', line, re.IGNORECASE):
            content_found = True

    result = '\n'.join(block).strip()
    if not content_found and len(block) <= 2:
        return None
    return result


def extract_lid(article_text, lid):
    lines = [line.strip() for line in article_text.split('\n') if line.strip()]
    start = None

    for index, line in enumerate(lines):
        if re.match(rf'^{re.escape(lid)}[.:)]\s+', line):
            start = index
            break
    if start is None:
        return None

    block = [lines[start]]
    for line in lines[start + 1:]:
        if re.match(r'^\d+[.:)]\s+', line):
            break
        if re.match(r'^Artikel\s+[0-9A-Za-z:.]+(?:\b|[\s.:-])', line, re.IGNORECASE):
            break
        block.append(line)

    return '\n'.join(block).strip()


def extract_from_tekst_variant(url, article, lid):
    response = SESSION.get(build_tekst_url(url), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    text = normalize_text(soup.get_text('\n', strip=True))
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    article_text = extract_article(lines, article)
    if not article_text:
        return None
    if lid:
        lid_text = extract_lid(article_text, lid)
        if lid_text:
            return lid_text
    return article_text


def extract_from_html_variant(url, article, lid):
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    main = soup.select_one('#content') or soup.select_one('main') or soup.body
    lines = clean_lines(main.stripped_strings if main else soup.stripped_strings)
    article_text = extract_article(lines, article)
    if not article_text:
        return None
    if lid:
        lid_text = extract_lid(article_text, lid)
        if lid_text:
            return lid_text
    return article_text


def extract_text(url, article, lid):
    parsed = urlparse(url)
    if 'wetten.overheid.nl' not in parsed.netloc:
        return 'Geen ondersteunde bron voor exacte wettekst.'

    try:
        result = extract_from_tekst_variant(url, article, lid)
        if result:
            return result
    except Exception:
        pass

    try:
        result = extract_from_html_variant(url, article, lid)
        if result:
            return result
    except Exception:
        pass

    return 'Artikel niet gevonden op de bronpagina.'


def build_cache():
    cards, skipped = load_source_cards()
    cached_cards = []
    errors = []

    for index, card in enumerate(cards, start=1):
        cached_card = dict(card)
        try:
            cached_card['back'] = extract_text(card['url'], card['article'], card['lid'])
        except Exception as exc:
            cached_card['back'] = f'Fout bij ophalen van de wettekst: {exc}'
            errors.append(card['reference'])
        cached_cards.append(cached_card)
        print(f"[{index}/{len(cards)}] {card['label']}")

    payload = {
        'cards': cached_cards,
        'errors': errors,
        'skipped': [{'reference': ref, 'reason': reason} for ref, reason in skipped],
    }
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Klaar. Cache geschreven naar: {CACHE_FILE}")
    print(f"Kaarten: {len(cached_cards)} | fouten: {len(errors)} | overgeslagen: {len(skipped)}")


if __name__ == '__main__':
    build_cache()
