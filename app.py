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
USER_AGENT = 'Mozilla/5.0'
REQUEST_TIMEOUT = 20

ARTICLE_RE = re.compile(r'\bArtikel\s*:?\s*([^\n]+?)(?=(?:\s+Lid\s*:?\s*|\s*→|$))', re.I)
LID_RE = re.compile(r'\bLid\s*:?\s*(\d+)', re.I)

NOISE = [
    'Toon relaties in LiDO','Maak een permanente link',
    'Toon wetstechnische informatie','Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op','...'
]

def normalize(t):
    return re.sub(r'\s+', ' ', html.unescape(t or '').replace('\xa0',' ')).strip()

def article_matches(a, b):
    a = normalize(a).lower().replace('.', ':')
    b = normalize(b).lower().replace('.', ':')
    return a == b

def parse_article(line):
    line = normalize(line)
    m = re.match(r'^Artikel\s+([\d:.a-zA-Z]+)\b', line)
    if not m:
        return None
    return m.group(1), normalize(line[m.end():])

def is_new_article_heading(line):
    line = normalize(line)
    return bool(re.match(r'^Artikel\s+[\d:.a-zA-Z]+\b', line))

def page_lines(txt):
    soup = BeautifulSoup(txt, 'html.parser')
    root = soup.select_one('#content') or soup.body or soup
    out = []
    for l in root.get_text('\n').splitlines():
        l = normalize(l)
        if l and l not in NOISE:
            out.append(l)
    return out

def extract_article(lines, wanted):
    block = []
    started = False

    for line in lines:
        parsed = parse_article(line)

        if parsed and article_matches(parsed[0], wanted):
            started = True
            block.append(f'Artikel {wanted}')
            if parsed[1]:
                block.append(parsed[1])
            continue

        if not started:
            continue

        if is_new_article_heading(line):
            next_parsed = parse_article(line)
            if next_parsed and not article_matches(next_parsed[0], wanted):
                break

        block.append(line)

    if block:
        return block

    for i, line in enumerate(lines):
        if re.match(rf'^Artikel\s+{re.escape(wanted)}\b', line):
            return [f'Artikel {wanted}'] + lines[i+1:i+10]

    return None

def extract_lid(block_lines, wanted_lid):
    if not block_lines or not wanted_lid:
        return '\n'.join(block_lines or [])

    lid_lines = []
    capture = False

    for line in block_lines:
        if re.match(rf'^{wanted_lid}[.:)]?\b', line):
            capture = True
            lid_lines.append(line)
            continue

        if capture and re.match(r'^\d+[.:)]?\b', line):
            break

        if capture:
            lid_lines.append(line)

    return '\n'.join(lid_lines) if lid_lines else '\n'.join(block_lines)

def extract(url, article, source_text):
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        lines = page_lines(r.text)
        block = extract_article(lines, article)

        if block:
            lid_match = LID_RE.search(source_text or '')
            lid = lid_match.group(1) if lid_match else None
            return extract_lid(block, lid)

    except Exception:
        pass

    return 'Artikel tekst niet gevonden op pagina.'

def load_cards():
    cards = []
    for line in SOURCE_FILE.read_text(encoding='utf-8').splitlines():
        if '→' not in line:
            continue

        left, right = line.split('→', 1)
        source_text = normalize(left.replace('*', ''))
        description = source_text

        link = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', right)
        art = ARTICLE_RE.search(source_text)

        if link and art:
            cards.append({
                'front': normalize(link.group(1)),
                'title': description,
                'url': link.group(2),
                'article': normalize(art.group(1)),
                'source_text': source_text
            })
    return cards

def main():
    st.set_page_config(page_title='Q4 Flashcards', layout='wide')

    cards = load_cards()
    if not cards:
        st.error('Geen kaarten gevonden.')
        return

    if 'card' not in st.session_state:
        st.session_state.card = random.choice(cards)
    if 'back' not in st.session_state:
        st.session_state.back = ''
    if 'answer_open' not in st.session_state:
        st.session_state.answer_open = False

    if st.button('Nieuwe kaart'):
        st.session_state.card = random.choice(cards)
        st.session_state.back = ''
        st.session_state.answer_open = False
        st.rerun()

    c = st.session_state.card

    st.subheader(c['title'])
    st.info(c['front'])
    st.markdown(f"[Open wet]({c['url']})")

    if not st.session_state.back:
        st.session_state.back = extract(c['url'], c['article'], c['source_text'])

    with st.expander('Antwoord', expanded=st.session_state.answer_open):
        st.text_area('Wettekst', st.session_state.back, height=300)

if __name__ == '__main__':
    main()
