import html
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/1.1)'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)


def parse_line(line: str):
    line = line.strip()
    if not line.startswith('* '):
        return None

    body = line[2:].strip()
    if '→' not in body:
        return {'skip': True, 'reason': 'geen pijl'}

    ref, rest = body.split('→', 1)
    ref = ref.strip()
    rest = rest.strip()

    desc_match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', rest)
    if not desc_match:
        return {'skip': True, 'reason': 'link niet parsebaar', 'reference': ref}

    desc = desc_match.group(1).strip()
    url = desc_match.group(2).strip()

    article_match = ARTICLE_RE.search(ref)
    if not article_match:
        return {'skip': True, 'reason': 'complete regeling of wet', 'reference': ref}

    article = article_match.group(1).strip()
    lid_match = LID_RE.search(ref)
    lid = lid_match.group(1).strip() if lid_match else None
    law_name = ref.split(' Artikel:')[0].strip()

    label_parts = [law_name, f'artikel {article}']
    if lid:
        label_parts.append(f'lid {lid}')

    return {
        'skip': False,
        'law': law_name,
        'article': article,
        'lid': lid,
        'reference': ref,
        'front': desc,
        'url': url,
        'label': ', '.join(label_parts),
    }


@st.cache_data(show_spinner=False)
def load_cards():
    md_text = DATA_FILE.read_text(encoding='utf-8')
    cards = []
    skipped = []

    for raw_line in md_text.splitlines():
        parsed = parse_line(raw_line)
        if not parsed:
            continue
        if parsed.get('skip'):
            skipped.append((parsed.get('reference', raw_line.strip()), parsed['reason']))
            continue
        cards.append(parsed)

    return cards, skipped


def _select_article_block(soup: BeautifulSoup, article: str):
    escaped = re.escape(article)
    for element in soup.find_all(id=True):
        if re.search(rf'artikel[.\-:_]?{escaped}\b', element['id'], re.IGNORECASE):
            return element
    return soup.select_one('div.artikel, article, div[class*="artikel"]') or soup.body


def _select_lid_block(block, lid: str):
    escaped = re.escape(lid)
    for element in block.find_all(id=True):
        if re.search(rf'lid[.\-:_]?{escaped}\b', element['id'], re.IGNORECASE):
            return element
    return block


def extract_exact_text_from_wetten(url: str) -> str:
    parsed = urlparse(url)
    if 'wetten.overheid.nl' not in parsed.netloc:
        return 'Geen ondersteunde bron voor exacte wettekst.'

    params = parse_qs(parsed.query)
    article = params.get('artikel', [None])[0]
    lid = params.get('lid', [None])[0]

    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    block = _select_article_block(soup, article) if article else soup.body
    if lid and block:
        block = _select_lid_block(block, lid)

    text = block.get_text('\n', strip=True) if block else soup.get_text('\n', strip=True)
    text = html.unescape(text)
    text = re.sub(r'\n{2,}', '\n\n', text).strip()
    return text or 'Geen tekst gevonden.'


@st.cache_data(show_spinner=True)
def get_back_text(url: str) -> str:
    try:
        return extract_exact_text_from_wetten(url)
    except Exception as exc:
        return f'Fout bij ophalen van de wettekst: {exc}'


def pick_new_card(cards, current_reference=None):
    if not cards:
        return None
    if len(cards) == 1:
        return cards[0]
    filtered = [card for card in cards if card['reference'] != current_reference]
    return random.choice(filtered or cards)


def main():
    st.set_page_config(page_title='Q4 flashcards', page_icon='⚖️', layout='centered')
    st.title('Q4 flashcards')

    cards, skipped = load_cards()
    st.caption(f'{len(cards)} kaartjes geladen. {len(skipped)} regels overgeslagen.')

    if not cards:
        st.error('Geen bruikbare regels gevonden in het bronbestand.')
        return

    if 'current_card' not in st.session_state:
        st.session_state.current_card = pick_new_card(cards)
        st.session_state.show_back = False

    col1, col2 = st.columns(2)
    with col1:
        if st.button('Nieuwe kaart', use_container_width=True):
            current_ref = st.session_state.current_card['reference'] if st.session_state.current_card else None
            st.session_state.current_card = pick_new_card(cards, current_ref)
            st.session_state.show_back = False
            st.rerun()
    with col2:
        if st.button('Draai kaart', use_container_width=True):
            st.session_state.show_back = not st.session_state.show_back
            st.rerun()

    card = st.session_state.current_card
    st.subheader(card['label'])
    st.markdown(f'**Voorkant:** {card["front"]}')
    st.markdown(f'**Bronregel:** {card["reference"]}')
    st.markdown(f'**URL:** {card["url"]}')

    if st.session_state.show_back:
        st.markdown('### Achterkant')
        st.text_area('Exacte wettekst', get_back_text(card['url']), height=420)
    else:
        st.info('Klik op **Draai kaart** voor de exacte wettekst.')

    with st.expander('Overgeslagen regels'):
        for item, reason in skipped:
            st.write(f'- {item} ({reason})')

    st.caption('Start met: streamlit run app.py')


if __name__ == '__main__':
    main()
