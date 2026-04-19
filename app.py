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
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/1.0)'

LINE_RE = re.compile(
    r'^\*\s+(?P<ref>.+?)\s*→\s*\+\+\[(?P<desc>.+?)\]\((?P<url>https?://[^)]+)\)\+\+\s*$'
)
ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)


def parse_markdown(md_text: str):
    cards = []
    skipped = []

    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line.startswith('* '):
            continue

        match = LINE_RE.match(line)
        if not match:
            skipped.append((line, 'parse'))
            continue

        ref = match.group('ref').strip()
        desc = match.group('desc').strip()
        url = match.group('url').strip()

        article_match = ARTICLE_RE.search(ref)
        if not article_match:
            skipped.append((ref, 'complete regeling of wet'))
            continue

        article = article_match.group(1).strip()
        lid_match = LID_RE.search(ref)
        lid = lid_match.group(1).strip() if lid_match else None

        law_name = ref.split(' Artikel:')[0].strip()
        label_parts = [law_name, f'artikel {article}']
        if lid:
            label_parts.append(f'lid {lid}')

        cards.append(
            {
                'law': law_name,
                'article': article,
                'lid': lid,
                'reference': ref,
                'front': desc,
                'url': url,
                'label': ', '.join(label_parts),
            }
        )

    return cards, skipped


def _select_article_block(soup: BeautifulSoup, article: str):
    selectors = [
        f'[id*="artikel.{article}"]',
        f'[id*="artikel-{article}"]',
        f'[id*="Artikel.{article}"]',
        f'[id*="Artikel-{article}"]',
    ]
    for selector in selectors:
        found = soup.select(selector)
        if found:
            return found[0]
    return soup.select_one('div.artikel, article, div[class*="artikel"]') or soup.body


def _select_lid_block(block, lid: str):
    selectors = [
        f'[id*="lid.{lid}"]',
        f'[id*="lid-{lid}"]',
        f'[id*="Lid.{lid}"]',
        f'[id*="Lid-{lid}"]',
    ]
    for selector in selectors:
        found = block.select(selector)
        if found:
            return found[0]
    return block


def extract_exact_text_from_wetten(url: str) -> str:
    parsed = urlparse(url)
    if 'wetten.overheid.nl' not in parsed.netloc:
        return 'Geen ondersteunde bron voor exacte wettekst.'

    params = parse_qs(parsed.query)
    article = params.get('artikel', [None])[0]
    lid = params.get('lid', [None])[0]

    response = requests.get(
        url,
        headers={'User-Agent': USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    block = _select_article_block(soup, article) if article else soup.body
    if lid and block:
        block = _select_lid_block(block, lid)

    text = block.get_text('\n', strip=True) if block else soup.get_text('\n', strip=True)
    text = html.unescape(text)
    text = re.sub(r'\n{2,}', '\n\n', text).strip()
    return text or 'Geen tekst gevonden.'


@st.cache_data(show_spinner=False)
def load_cards():
    md_text = DATA_FILE.read_text(encoding='utf-8')
    return parse_markdown(md_text)


@st.cache_data(show_spinner=True)
def get_back_text(url: str) -> str:
    try:
        return extract_exact_text_from_wetten(url)
    except Exception as exc:
        return f'Fout bij ophalen van de wettekst: {exc}'


def pick_new_card(cards):
    return random.choice(cards) if cards else None


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
            st.session_state.current_card = pick_new_card(cards)
            st.session_state.show_back = False
            st.rerun()
    with col2:
        if st.button('Draai kaart', use_container_width=True):
            st.session_state.show_back = not st.session_state.show_back
            st.rerun()

    card = st.session_state.current_card
    st.subheader(card['label'])
    st.markdown(f'**Bronregel:** {card["reference"]}')

    if st.session_state.show_back:
        st.markdown('### Achterkant')
        back_text = get_back_text(card['url'])
        st.text_area('Exacte wettekst', back_text, height=420)
    else:
        st.markdown('### Voorkant')
        st.markdown(card['front'])

    with st.expander('Overgeslagen regels'):
        for item, reason in skipped:
            st.write(f'- {item} ({reason})')

    st.caption('Start met: streamlit run app.py')


if __name__ == '__main__':
    main()
