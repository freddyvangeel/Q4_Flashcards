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
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/1.2)'

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


def _normalize_text(text: str) -> str:
    text = html.unescape(text or '')
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\r', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _find_best_article_container(soup: BeautifulSoup, article: str):
    article_text = str(article).strip()
    escaped = re.escape(article_text)

    id_patterns = [
        rf'artikel[.\-:_]?{escaped}(?:\b|$)',
        rf'art[.\-:_]?{escaped}(?:\b|$)',
    ]
    for element in soup.find_all(id=True):
        element_id = element.get('id', '')
        if any(re.search(pattern, element_id, re.IGNORECASE) for pattern in id_patterns):
            return element

    text_patterns = [
        rf'^artikel\s+{escaped}[\s.:]',
        rf'^artikel\s+{escaped}$',
    ]
    candidate_tags = ['article', 'div', 'section']
    for tag in candidate_tags:
        for element in soup.find_all(tag):
            text = _normalize_text(element.get_text('\n', strip=True))
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in text_patterns):
                return element

    for element in soup.find_all(['article', 'div', 'section', 'li']):
        text = _normalize_text(element.get_text('\n', strip=True))
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in text_patterns):
            return element

    return None


def _find_lid_text(article_text: str, lid: str) -> str | None:
    lid_value = str(lid).strip()
    escaped = re.escape(lid_value)
    text = article_text.replace('\r\n', '\n')
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    numbered_lines = []
    for line in lines:
        if re.match(r'^\d+[.:)]?\s+', line):
            numbered_lines.append(line)

    if numbered_lines:
        collecting = False
        collected = []
        for line in numbered_lines:
            if re.match(rf'^{escaped}[.:)]?\s+', line):
                collecting = True
                collected = [line]
                continue
            if collecting and re.match(r'^\d+[.:)]?\s+', line):
                break
            if collecting:
                collected.append(line)
        if collected:
            return _normalize_text('\n'.join(collected))

    block_pattern = re.compile(
        rf'(^|\n){escaped}[.:)]?\s+.*?(?=(\n\d+[.:)]?\s+|$))',
        re.IGNORECASE | re.DOTALL,
    )
    match = block_pattern.search(text)
    if match:
        return _normalize_text(match.group(0))

    return None


def extract_exact_text_from_wetten(url: str, article_hint: str | None = None, lid_hint: str | None = None) -> str:
    parsed = urlparse(url)
    if 'wetten.overheid.nl' not in parsed.netloc:
        return 'Geen ondersteunde bron voor exacte wettekst.'

    params = parse_qs(parsed.query)
    article = params.get('artikel', [None])[0] or article_hint
    lid = params.get('lid', [None])[0] or lid_hint

    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    container = _find_best_article_container(soup, article) if article else None
    page_text = _normalize_text(soup.get_text('\n', strip=True))

    if not container:
        return page_text

    article_text = _normalize_text(container.get_text('\n', strip=True))
    if lid:
        lid_text = _find_lid_text(article_text, lid)
        if lid_text:
            return lid_text

    return article_text or page_text


@st.cache_data(show_spinner=True)
def get_back_text(url: str, article: str | None, lid: str | None) -> str:
    try:
        return extract_exact_text_from_wetten(url, article, lid)
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

    if st.session_state.show_back:
        st.markdown('### Achterkant')
        back_text = get_back_text(card['url'], card['article'], card['lid'])
        st.text_area('Exacte wettekst', back_text, height=420)
    else:
        st.info('Klik op **Draai kaart** voor de exacte wettekst.')

    with st.expander('Overgeslagen regels'):
        for item, reason in skipped:
            st.write(f'- {item} ({reason})')

    st.caption('Start met: streamlit run app.py')


if __name__ == '__main__':
    main()
