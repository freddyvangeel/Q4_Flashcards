import html
import json
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# --- configuratie ---
CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
SOURCE_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
REQUEST_TIMEOUT = 20

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE_PHRASES = [
    'Toon relaties in LiDO',
    'Maak een permanente link',
    'Toon wetstechnische informatie',
    'Gegevens van deze regeling',
    'Vergelijk met andere versies',
    'Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling',
    'Selecteer een andere versie',
    'Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op',
]

HEADER_PATTERNS = [
    re.compile(r'^hoofdstuk\b', re.I),
    re.compile(r'^titeldeel\b', re.I),
    re.compile(r'^afdeling\b', re.I),
    re.compile(r'^paragraaf\b', re.I),
    re.compile(r'^§\s*\d+', re.I),
]


def read_cache_payload():
    if not CACHE_FILE.exists():
        return {'cards': []}
    try:
        return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'cards': []}


def write_cache_payload(payload):
    CACHE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def normalize_spaces(text: str) -> str:
    text = html.unescape(text or '').replace('\xa0', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def remove_noise(text: str) -> str:
    text = html.unescape(text or '').replace('\xa0', ' ')
    for phrase in NOISE_PHRASES:
        text = text.replace(phrase, ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_header_line(line: str) -> bool:
    line = normalize_spaces(line)
    return any(pattern.match(line) for pattern in HEADER_PATTERNS)


def is_noise_line(line: str) -> bool:
    line = normalize_spaces(line)
    if not line:
        return True
    if line in NOISE_PHRASES:
        return True
    if line == '...':
        return True
    return False


def format_article_text(text: str) -> str:
    text = remove_noise(text)
    text = re.sub(r' *\n *', '\n', text)
    return text.strip()


def tekst_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query['tekst'] = ['1']
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), ''))


def page_lines_from_html(raw_html: str) -> list[str]:
    soup = BeautifulSoup(raw_html, 'html.parser')
    root = soup.select_one('#content') or soup.body or soup
    raw = root.get_text('\n', strip=True)
    raw = html.unescape(raw).replace('\xa0', ' ')
    lines = []
    for line in raw.splitlines():
        line = normalize_spaces(line)
        if is_noise_line(line):
            continue
        lines.append(line)
    return lines


def extract_article_block_from_lines(lines: list[str], article_num: str) -> str | None:
    article_key = article_num.strip().lower()
    start_index = None

    for i, line in enumerate(lines):
        if re.match(rf'^artikel\s+{re.escape(article_num)}(?:\b|\s|\.|\(|\[)', line, re.I):
            start_index = i
            break

    if start_index is None:
        return None

    block = [lines[start_index]]
    for line in lines[start_index + 1:]:
        match = re.match(r'^artikel\s+(\d+[a-zA-Z]*)\b', line, re.I)
        if match and match.group(1).strip().lower() != article_key:
            break
        if is_header_line(line):
            break
        if is_noise_line(line):
            continue
        block.append(line)

    text = '\n'.join(block).strip()
    return format_article_text(text) if len(text) >= 20 else None


def extract_lid_block(article_text: str, lid: str) -> str | None:
    lid = (lid or '').strip()
    if not lid:
        return article_text

    lines = [line.strip() for line in article_text.splitlines() if line.strip()]
    start_index = None
    for i, line in enumerate(lines):
        if re.match(rf'^{re.escape(lid)}[.:)]?\b', line, re.I):
            start_index = i
            break

    if start_index is None:
        return article_text

    block = [lines[start_index]]
    for line in lines[start_index + 1:]:
        if re.match(r'^\d+[.:)]?\b', line):
            break
        block.append(line)
    return '\n'.join(block).strip()


def extract_from_url(url: str, article_num: str, lid: str | None = None) -> str | None:
    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    lines = page_lines_from_html(response.text)
    article_text = extract_article_block_from_lines(lines, article_num)
    if not article_text:
        return None
    return extract_lid_block(article_text, lid)


def extract(url, article_num, lid: str | None = None):
    try:
        result = extract_from_url(url, article_num, lid)
        if result:
            return result
    except Exception:
        pass

    try:
        result = extract_from_url(tekst_url(url), article_num, lid)
        if result:
            return result
    except Exception:
        pass

    return 'Artikel tekst niet gevonden op pagina.'


def persist(card, text):
    payload = read_cache_payload()
    cards = payload.get('cards', [])
    for existing in cards:
        if existing.get('id') == card['id']:
            existing['back'] = text
            break
    else:
        cached = dict(card)
        cached['back'] = text
        cards.append(cached)
    payload['cards'] = cards
    write_cache_payload(payload)


def get_cached_back(card):
    payload = read_cache_payload()
    for existing in payload.get('cards', []):
        if existing.get('id') == card['id'] and existing.get('back'):
            return existing['back']
    return ''


def parse_card_line(line: str):
    if '→' not in line:
        return None

    parts = line.split('→', 1)
    front_text = parts[0].replace('*', '').strip()
    link_match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', parts[1])
    if not link_match:
        return None

    desc, url = link_match.group(1).strip(), link_match.group(2).strip()
    article_match = ARTICLE_RE.search(front_text)
    if not article_match:
        return None

    article = article_match.group(1).strip()
    lid_match = LID_RE.search(front_text)
    lid = lid_match.group(1).strip() if lid_match else None
    law = front_text.split(' Artikel:')[0].strip().rstrip(',')

    return {
        'id': f'{law}_{article}_{lid or ""}_{desc}'[:160],
        'law': law,
        'article': article,
        'lid': lid,
        'front': desc,
        'url': url,
        'label': f'{law} - Art. {article}' + (f', lid {lid}' if lid else ''),
    }


def load_cards():
    if not SOURCE_FILE.exists():
        return []

    cards = []
    try:
        content = SOURCE_FILE.read_text(encoding='utf-8')
        for line in content.splitlines():
            card = parse_card_line(line)
            if not card:
                continue
            card['back'] = get_cached_back(card)
            cards.append(card)
    except Exception:
        st.error('Fout bij lezen bronbestand.')
    return cards


def main():
    st.set_page_config(page_title='Q4 Flashcards', layout='wide')

    cards = load_cards()
    if not cards:
        st.error(f'Bestand {SOURCE_FILE.name} is leeg of ontbreekt.')
        return

    laws = sorted({c['law'] for c in cards})
    sel = st.sidebar.multiselect('Wetten', ['Alle'] + laws, default=['Alle'])
    filtered = cards if 'Alle' in sel else [c for c in cards if c['law'] in sel]

    if not filtered:
        st.warning('Geen kaarten voor deze selectie.')
        return

    valid_ids = [c['id'] for c in filtered]
    if 'card' not in st.session_state or st.session_state.card not in valid_ids:
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = st.session_state.card_obj.get('back', '')

    c = st.session_state.card_obj

    col1, col2 = st.columns(2)
    if col1.button('Volgende 🎲'):
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = st.session_state.card_obj.get('back', '')
        st.rerun()

    if col2.button('Herlaad 🔄'):
        st.session_state.back = extract(c['url'], c['article'], c.get('lid'))
        persist(c, st.session_state.back)
        st.rerun()

    st.divider()
    st.subheader(c['label'])
    st.info(c['front'])
    st.caption(f'[Link naar wet]({c["url"]})')

    if not st.session_state.back:
        with st.spinner('Laden...'):
            st.session_state.back = extract(c['url'], c['article'], c.get('lid'))
            persist(c, st.session_state.back)

    with st.expander('Antwoord', expanded=False):
        st.text_area('Wettekst', st.session_state.back, height=300)

if __name__ == '__main__':
    main()
