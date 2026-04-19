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
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/1.5)'
ALL_LAWS_LABEL = 'Alle wetten'

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


def _remove_noise_lines(text: str) -> str:
    cleaned_lines = []
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if line in NOISE_PHRASES:
            continue
        if line == '...':
            continue
        cleaned_lines.append(line)
    return _normalize_text('\n'.join(cleaned_lines))


def _looks_like_article_start(text: str, article: str) -> bool:
    escaped = re.escape(str(article).strip())
    patterns = [
        rf'^artikel\s+{escaped}(?:\b|[\s.:])',
        rf'^art\.\s*{escaped}(?:\b|[\s.:])',
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _find_best_article_container(soup: BeautifulSoup, article: str):
    article_text = str(article).strip()
    escaped = re.escape(article_text)

    for element in soup.find_all(id=True):
        element_id = element.get('id', '')
        if re.search(rf'artikel[.\-:_]?{escaped}(?:\b|$)', element_id, re.IGNORECASE):
            return element

    candidate_tags = ['article', 'div', 'section', 'li']
    for element in soup.find_all(candidate_tags):
        text = _remove_noise_lines(_normalize_text(element.get_text('\n', strip=True)))
        if _looks_like_article_start(text, article_text):
            return element

    return None


def _extract_article_text_from_page(page_text: str, article: str) -> str | None:
    escaped = re.escape(str(article).strip())
    pattern = re.compile(
        rf'(artikel\s+{escaped}(?:\b|[\s.:]).*?)(?=\nartikel\s+[0-9a-zA-Z:.]+(?:\b|[\s.:])|$)',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(page_text)
    if match:
        return _remove_noise_lines(match.group(1))
    return None


def _find_lid_text(article_text: str, lid: str) -> str | None:
    lid_value = str(lid).strip()
    escaped = re.escape(lid_value)
    text = article_text.replace('\r\n', '\n')
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    numbered_lines = [line for line in lines if re.match(r'^\d+[.:)]?\s+', line)]
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
            return _remove_noise_lines('\n'.join(collected))

    block_pattern = re.compile(
        rf'(^|\n){escaped}[.:)]?\s+.*?(?=(\n\d+[.:)]?\s+|$))',
        re.IGNORECASE | re.DOTALL,
    )
    match = block_pattern.search(text)
    if match:
        return _remove_noise_lines(match.group(0))

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
    page_text = _remove_noise_lines(_normalize_text(soup.get_text('\n', strip=True)))

    article_text = None
    container = _find_best_article_container(soup, article) if article else None
    if container:
        candidate = _remove_noise_lines(_normalize_text(container.get_text('\n', strip=True)))
        if _looks_like_article_start(candidate, article):
            article_text = candidate

    if not article_text and article:
        article_text = _extract_article_text_from_page(page_text, article)

    if not article_text:
        return 'Artikel of lid niet exact gevonden op de bronpagina.'

    if lid:
        lid_text = _find_lid_text(article_text, lid)
        if lid_text:
            return lid_text
        return f'Lid {lid} niet exact gevonden binnen artikel {article}.\n\n{article_text}'

    return article_text


@st.cache_data(show_spinner=True)
def get_back_text(url: str, article: str | None, lid: str | None) -> str:
    try:
        return extract_exact_text_from_wetten(url, article, lid)
    except Exception as exc:
        return f'Fout bij ophalen van de wettekst: {exc}'


def get_law_options(cards):
    laws = sorted({card['law'] for card in cards})
    return [ALL_LAWS_LABEL] + laws


def filter_cards_by_laws(cards, selected_laws):
    if not selected_laws or ALL_LAWS_LABEL in selected_laws:
        return cards
    return [card for card in cards if card['law'] in selected_laws]


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
    law_options = get_law_options(cards)

    selected_laws = st.multiselect(
        'Filter op wet',
        options=law_options,
        default=[ALL_LAWS_LABEL],
    )

    filtered_cards = filter_cards_by_laws(cards, selected_laws)
    st.caption(f'{len(filtered_cards)} kaartjes beschikbaar. {len(skipped)} regels overgeslagen.')

    if not filtered_cards:
        st.error('Geen bruikbare kaartjes binnen deze selectie.')
        return

    current_card = st.session_state.get('current_card')
    if not current_card or current_card['reference'] not in {card['reference'] for card in filtered_cards}:
        st.session_state.current_card = pick_new_card(filtered_cards)
        st.session_state.show_back = False

    col1, col2 = st.columns(2)
    with col1:
        if st.button('Nieuwe kaart', use_container_width=True):
            current_ref = st.session_state.current_card['reference'] if st.session_state.current_card else None
            st.session_state.current_card = pick_new_card(filtered_cards, current_ref)
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
