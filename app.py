import json
import random
from pathlib import Path

import streamlit as st

CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
ALL_LAWS_LABEL = 'Alle wetten'


def load_cached_cards():
    if not CACHE_FILE.exists():
        raise FileNotFoundError('flashcards_cache.json ontbreekt. Run eerst build_cache.py en commit het resultaat.')

    payload = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    cards = payload.get('cards', [])
    errors = payload.get('errors', [])
    return cards, errors


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
    st.session_state.back_text = card.get('back', '')


def main():
    st.set_page_config(page_title='Q4 flashcards', page_icon='⚖️', layout='centered')
    st.title('Q4 flashcards')

    try:
        cards, errors = load_cached_cards()
    except Exception as exc:
        st.error(str(exc))
        return

    law_options = get_law_options(cards)
    selected_laws = st.multiselect(
        'Filter op wet',
        options=law_options,
        default=[ALL_LAWS_LABEL],
        key='law_filter',
    )

    filtered_cards = filter_cards_by_laws(cards, selected_laws)
    st.caption(f'{len(filtered_cards)} kaartjes beschikbaar. Lokale cache: {len(cards)} kaartjes.')

    if not filtered_cards:
        st.error('Geen bruikbare kaartjes binnen deze selectie.')
        return

    current_card = st.session_state.get('current_card')
    valid_refs = {card['reference'] for card in filtered_cards}
    if not current_card or current_card['reference'] not in valid_refs:
        set_current_card(pick_new_card(filtered_cards))

    if st.button('Nieuwe kaart', use_container_width=True):
        current_ref = st.session_state.current_card['reference'] if st.session_state.current_card else None
        set_current_card(pick_new_card(filtered_cards, current_ref))
        st.rerun()

    card = st.session_state.current_card
    st.subheader(card['label'])
    st.write(card['front'])

    with st.expander('Achterkant', expanded=False):
        st.text_area('Wettekst', st.session_state.get('back_text', ''), height=420)

    if errors:
        with st.expander('Cachefouten', expanded=False):
            for item in errors:
                st.write(f'- {item}')


if __name__ == '__main__':
    main()
