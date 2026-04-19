import html
import json
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
SOURCE_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
ALL_LAWS_LABEL = 'Alle wetten'
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/5.1)'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE = {
    'Toon relaties in LiDO', 'Maak een permanente link', 'Toon wetstechnische informatie',
    'Gegevens van deze regeling', 'Vergelijk met andere versies', 'Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling', 'Selecteer een andere versie', 'Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op', 'Permalink', '...'
}


def normalize_text(text: str) -> str:
    text = html.unescape(text or '').replace('\xa0', ' ')
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_extracted_text(text: str) -> str:
    lines = []
    for raw in text.split('\n'):
        line = normalize_text(raw)
        if not line or line in NOISE:
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def tekst_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params['tekst'] = ['1']
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(params, doseq=True), parsed.fragment))


def parse_line(line: str):
    line = line.strip()
    if not line.startswith('* '):
        return None
    body = line[2:].strip()
    if '→' not in body:
        return {'skip': True}

    ref, rest = body.split('→', 1)
    ref = ref.strip()
    match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', rest)
    if not match:
        return {'skip': True}

    desc, url = match.group(1).strip(), match.group(2).strip()
    article_match = ARTICLE_RE.search(ref)
    if not article_match:
        return {'skip': True}

    article = article_match.group(1).strip()
    lid_match = LID_RE.search(ref)
    lid = lid_match.group(1).strip() if lid_match else None
    law = ref.split(' Artikel:')[0].strip()
    label = f"{law}, artikel {article}" + (f", lid {lid}" if lid else "")
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


@st.cache_data(show_spinner=False)
def load_source_cards():
    text = SOURCE_FILE.read_text(encoding='utf-8')
    return [parsed for raw in text.splitlines() if (parsed := parse_line(raw)) and not parsed.get('skip')]


def read_cache_payload():
    if not CACHE_FILE.exists():
        return {'cards': [], 'errors': []}
    try:
        return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'cards': [], 'errors': []}


def write_cache_payload(payload):
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def load_cards():
    source_cards = load_source_cards()
    by_reference = {card['reference']: dict(card) for card in source_cards}
    payload = read_cache_payload()
    for cached in payload.get('cards', []):
        ref = cached.get('reference')
        if ref in by_reference and cached.get('back'):
            by_reference[ref]['back'] = cached['back']
    return list(by_reference.values()), payload.get('errors', [])


def find_article_container(soup: BeautifulSoup, article: str):
    article = article.strip().lower()

    # 1. Find explicit heading text like "Artikel 96b" or "Artikel 3. (...)"
    heading_pattern = re.compile(rf'^artikel\s+{re.escape(article)}(?:\b|\s|\.|\(|\[)', re.IGNORECASE)
    heading_tags = ['h1', 'h2', 'h3', 'h4', 'strong', 'b', 'div', 'span', 'a']

    for tag in heading_tags:
        for node in soup.find_all(tag):
            text = normalize_text(node.get_text(' ', strip=True))
            if heading_pattern.match(text):
                # prefer the nearest block-level wrapper that likely contains the article content
                for parent in [node] + list(node.parents):
                    name = getattr(parent, 'name', '')
                    if name in {'article', 'section', 'div', 'li'}:
                        parent_text = clean_extracted_text(parent.get_text('\n', strip=True))
                        if heading_pattern.search(parent_text.lower()):
                            return parent
                return node

    # 2. Find any element id that references the article
    id_pattern = re.compile(rf'(artikel|art)[\-:_ ]?{re.escape(article)}\b', re.IGNORECASE)
    for node in soup.find_all(attrs={'id': True}):
        if id_pattern.search(str(node.get('id', ''))):
            return node

    return None


def extract_article_from_container(container, article: str) -> str | None:
    text = clean_extracted_text(container.get_text('\n', strip=True))
    if not text:
        return None

    start_pattern = re.compile(rf'(?im)^artikel\s+{re.escape(article)}(?:\b[^\n]*)?$')
    start_match = start_pattern.search(text)
    if not start_match:
        # fallback: return full container if it clearly starts with the article heading
        first_line = text.split('\n', 1)[0].strip()
        if re.match(rf'^artikel\s+{re.escape(article)}(?:\b|\s|\.|\(|\[)', first_line, re.IGNORECASE):
            return text
        return None

    next_article_pattern = re.compile(r'(?im)^artikel\s+\d+[a-zA-Z]*(?:\b[^\n]*)?$')
    end = len(text)
    for match in next_article_pattern.finditer(text, start_match.end()):
        end = match.start()
        break
    return text[start_match.start():end].strip()


def extract_lid_block(article_text: str, lid: str) -> str | None:
    lid_escaped = re.escape(lid.strip())
    start_pattern = re.compile(rf'(?m)^\s*{lid_escaped}[.:)]?\s+')
    start_match = start_pattern.search(article_text)
    if not start_match:
        return None

    next_lid_pattern = re.compile(r'(?m)^\s*\d+[.:)]?\s+')
    end = len(article_text)
    next_match = next_lid_pattern.search(article_text, start_match.end())
    if next_match:
        end = next_match.start()
    return article_text[start_match.start():end].strip()


def extract_from_url(url: str, article: str, lid: str | None) -> str | None:
    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    container = find_article_container(soup, article)
    if container is None:
        return None

    article_text = extract_article_from_container(container, article)
    if not article_text:
        return None

    if lid:
        lid_text = extract_lid_block(article_text, lid)
        if lid_text:
            return lid_text
    return article_text


def extract(url: str, article: str, lid: str | None) -> str:
    try:
        result = extract_from_url(url, article, lid)
        if result:
            return result
    except Exception:
        pass

    try:
        result = extract_from_url(tekst_url(url), article, lid)
        if result:
            return result
    except Exception:
        pass

    return 'Artikel niet gevonden'


def persist(card, text):
    payload = read_cache_payload()
    cards = payload.get('cards', [])
    for existing in cards:
        if existing['reference'] == card['reference']:
            existing['back'] = text
            break
    else:
        new_card = dict(card)
        new_card['back'] = text
        cards.append(new_card)
    payload['cards'] = cards
    write_cache_payload(payload)


def get_back(card):
    if card.get('back'):
        return card['back']
    text = extract(card['url'], card['article'], card['lid'])
    persist(card, text)
    card['back'] = text
    return text


def reload_card():
    card = st.session_state.get('current_card')
    if not card:
        return
    text = extract(card['url'], card['article'], card['lid'])
    persist(card, text)
    st.session_state.current_card['back'] = text
    st.session_state.back_text = text


def main():
    st.title('Q4 flashcards')

    cards, _ = load_cards()
    laws = sorted({card['law'] for card in cards})
    selection = st.multiselect('Filter op wet', [ALL_LAWS_LABEL] + laws, default=[ALL_LAWS_LABEL])
    if ALL_LAWS_LABEL not in selection:
        cards = [card for card in cards if card['law'] in selection]

    if 'current_card' not in st.session_state:
        st.session_state.current_card = random.choice(cards)
        st.session_state.back_text = get_back(st.session_state.current_card)

    col1, col2 = st.columns(2)
    with col1:
        if st.button('Nieuwe kaart'):
            st.session_state.current_card = random.choice(cards)
            st.session_state.back_text = get_back(st.session_state.current_card)
    with col2:
        if st.button('Herlaad wet'):
            reload_card()

    card = st.session_state.current_card
    st.subheader(card['label'])
    st.markdown(f'<a href="{card["url"]}" target="_blank">{card["front"]}</a>', unsafe_allow_html=True)

    with st.expander('Achterkant'):
        st.text_area('Wettekst', st.session_state.back_text, height=420)


if __name__ == '__main__':
    main()
