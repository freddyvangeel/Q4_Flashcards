import html
import random
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/2.1)'
ALL_LAWS_LABEL = 'Alle wetten'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE = {
    'Toon relaties in LiDO', 'Maak een permanente link', 'Toon wetstechnische informatie',
    'Gegevens van deze regeling', 'Vergelijk met andere versies', 'Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling', 'Selecteer een andere versie', 'Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op', 'Permalink', '...'
}


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


@st.cache_data(show_spinner=False)
def load_cards():
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


def clean_lines(strings):
    output = []
    for value in strings:
        value = html.unescape(value).replace('\xa0', ' ').strip()
        value = re.sub(r'\s+', ' ', value)
        if not value or value in NOISE:
            continue
        output.append(value)
    return output


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


def extract_text(url, article, lid):
    parsed = urlparse(url)
    if 'wetten.overheid.nl' not in parsed.netloc:
        return 'Geen ondersteunde bron voor exacte wettekst.'

    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    main = soup.select_one('#content') or soup.select_one('main') or soup.body
    lines = clean_lines(main.stripped_strings if main else soup.stripped_strings)

    article_text = extract_article(lines, article)
    if not article_text:
        return 'Artikel niet gevonden op de bronpagina.'

    if lid:
        lid_text = extract_lid(article_text, lid)
        if lid_text:
            return lid_text

    return article_text


@st.cache_data(show_spinner=True)
def get_text(url, article, lid):
    try:
        return extract_text(url, article, lid)
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


def set_current_card(card):
    st.session_state.current_card = card
    st.session_state.show_back = False
    st.session_state.back_text = get_text(card['url'], card['article'], card['lid'])


def main():
    st.set_page_config(page_title='Q4 flashcards', page_icon='⚖️', layout='centered')
    st.title('Q4 flashcards')

    cards, skipped = load_cards()
    law_options = get_law_options(cards)

    selected_laws = st.multiselect(
        'Filter op wet',
        options=law_options,
        default=[ALL_LAWS_LABEL],
        key='law_filter',
    )

    filtered_cards = filter_cards_by_laws(cards, selected_laws)
    st.caption(f'{len(filtered_cards)} kaartjes beschikbaar. {len(skipped)} regels overgeslagen.')

    if not filtered_cards:
        st.error('Geen bruikbare kaartjes binnen deze selectie.')
        return

    current_card = st.session_state.get('current_card')
    valid_refs = {card['reference'] for card in filtered_cards}
    if not current_card or current_card['reference'] not in valid_refs:
        set_current_card(pick_new_card(filtered_cards))

    col1, col2 = st.columns(2)
    with col1:
        if st.button('Nieuwe kaart', use_container_width=True):
            current_ref = st.session_state.current_card['reference'] if st.session_state.current_card else None
            set_current_card(pick_new_card(filtered_cards, current_ref))
            st.rerun()
    with col2:
        if st.button('Draai kaart', use_container_width=True):
            st.session_state.show_back = not st.session_state.show_back
            st.rerun()

    card = st.session_state.current_card
    st.subheader(card['label'])
    st.write(card['front'])

    with st.expander('Achterkant', expanded=st.session_state.show_back):
        st.text_area('Wettekst', st.session_state.get('back_text', ''), height=420)

    with st.expander('Overgeslagen regels'):
        for item, reason in skipped:
            st.write(f'- {item} ({reason})')


if __name__ == '__main__':
    main()
