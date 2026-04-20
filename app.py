import html
import json
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# --- Configuratie ---
CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
SOURCE_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
REQUEST_TIMEOUT = 20

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
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def clean_text(text: str) -> str:
    text = normalize_spaces(text)
    for phrase in NOISE_PHRASES:
        text = text.replace(phrase, ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'(?<!\d)(\b\d+\b)\s+', r'\n\1 ', text)
    text = re.sub(r'\s([a-z]\.)\s+', r'\n\1 ', text)
    return text.strip()


def tekst_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query['tekst'] = ['1']
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), ''))


def find_article_container(soup: BeautifulSoup, article_num: str):
    article_num = article_num.strip().lower()
    pattern = re.compile(rf'^artikel\s+{re.escape(article_num)}(?:\b|\s|\.|\(|\[)', re.I)

    for node in soup.find_all(['h1', 'h2', 'h3', 'div', 'span', 'strong', 'a']):
        txt = normalize_spaces(node.get_text(' ', strip=True)).lower()
        if pattern.match(txt):
            return node.find_parent(['article', 'section', 'div', 'li']) or node
    return None


def extract_article_block(text: str, article_num: str) -> str | None:
    article_key = article_num.strip().lower()
    start_pattern = re.compile(rf'(?im)^artikel\s+{re.escape(article_num)}(?:\b[^\n]*)?$')
    start_match = start_pattern.search(text)
    if not start_match:
        first_line = text.split('\n', 1)[0].strip()
        if re.match(rf'^artikel\s+{re.escape(article_num)}(?:\b|\s|\.|\(|\[)', first_line, re.I):
            return text.strip() if len(text.strip()) >= 20 else None
        return None

    next_article_pattern = re.compile(r'(?im)^artikel\s+(\d+[a-zA-Z]*)(?:\b[^\n]*)?$')
    end = len(text)
    for match in next_article_pattern.finditer(text, start_match.end()):
        if match.group(1).strip().lower() != article_key:
            end = match.start()
            break

    block = text[start_match.start():end].strip()
    return block if len(block) >= 20 else None


def extract_from_url(url: str, article_num: str) -> str | None:
    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    container = find_article_container(soup, article_num)
    if not container:
        return None

    text = clean_text(container.get_text(' '))
    return extract_article_block(text, article_num)


def extract(url, article_num):
    try:
        result = extract_from_url(url, article_num)
        if result:
            return result
    except Exception:
        pass

    try:
        result = extract_from_url(tekst_url(url), article_num)
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


def load_cards():
    if not SOURCE_FILE.exists():
        return []
    cards = []
    try:
        content = SOURCE_FILE.read_text(encoding='utf-8')
        for line in content.splitlines():
            if '→' not in line:
                continue
            parts = line.split('→', 1)
            front_text = parts[0].replace('*', '').strip()

            link_match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', parts[1])
            if not link_match:
                continue

            desc, url = link_match.group(1), link_match.group(2)
            art_match = re.search(r'Artikel\s*:\s*([^\s,]+)', front_text, re.I)
            article = art_match.group(1) if art_match else ''
            if not article:
                continue
            law = front_text.split('Artikel:')[0].strip().rstrip(',')

            card = {
                'id': f"{law}_{article}_{desc}"[:120],
                'law': law,
                'article': article,
                'front': desc,
                'url': url,
                'label': f"{law} - Art. {article}",
            }
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

    # Filter
    laws = sorted({c['law'] for c in cards})
    sel = st.sidebar.multiselect('Wetten', ['Alle'] + laws, default=['Alle'])
    filtered = cards if 'Alle' in sel else [c for c in cards if c['law'] in sel]

    if not filtered:
        st.warning('Geen kaarten voor deze selectie.')
        return

    # Session State
    valid_ids = [c['id'] for c in filtered]
    if 'card' not in st.session_state or st.session_state.card not in valid_ids:
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = st.session_state.card_obj.get('back', '')

    c = st.session_state.card_obj

    # Knoppen
    col1, col2 = st.columns(2)
    if col1.button('Volgende 🎲'):
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = st.session_state.card_obj.get('back', '')
        st.rerun()

    if col2.button('Herlaad 🔄'):
        st.session_state.back = extract(c['url'], c['article'])
        persist(c, st.session_state.back)
        st.rerun()

    # Content
    st.divider()
    st.subheader(c['label'])
    st.info(c['front'])
    st.caption(f'[Link naar wet]({c["url"]})')

    if not st.session_state.back:
        with st.spinner('Laden...'):
            st.session_state.back = extract(c['url'], c['article'])
            persist(c, st.session_state.back)

    with st.expander('Antwoord', expanded=False):
        st.text_area('Wettekst', st.session_state.back, height=300)

if __name__ == '__main__':
    main()
