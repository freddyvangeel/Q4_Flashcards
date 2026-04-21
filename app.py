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

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+)', re.I)
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
    m = re.match(r'^artikel\s+([\d:.a-zA-Z]+)(.*)$', line, re.I)
    if not m:
        return None
    return m.group(1), normalize(m.group(2))


def page_lines(txt):
    soup = BeautifulSoup(txt, 'html.parser')
    root = soup.select_one('#content') or soup.body
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

        if parsed and not article_matches(parsed[0], wanted):
            break

        block.append(line)

    return block if len(block) > 2 else None


def extract_lid(block_lines, wanted_lid):
    if not block_lines or not wanted_lid:
        return '\n'.join(block_lines or [])

    lid_lines = []
    capture = False

    for line in block_lines:
        if re.match(rf'^{wanted_lid}\b', line):
            capture = True
            lid_lines.append(line)
            continue

        if capture and re.match(r'^\d+\b', line):
            break

        if capture:
            lid_lines.append(line)

    return '\n'.join(lid_lines) if lid_lines else '\n'.join(block_lines)


def extract(url, article, front_text):
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        lines = page_lines(r.text)
        block = extract_article(lines, article)

        if block:
            lid_match = LID_RE.search(front_text or '')
            lid = lid_match.group(1) if lid_match else None
            return extract_lid(block, lid)

    except:
        pass
    return 'Artikel tekst niet gevonden op pagina.'


def load_cards():
    cards = []
    for line in SOURCE_FILE.read_text(encoding='utf-8').splitlines():
        if '→' not in line:
            continue
        m = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', line)
        art = ARTICLE_RE.search(line)
        if m and art:
            cards.append({
                'front': m.group(1),
                'url': m.group(2),
                'article': art.group(1).strip()
            })
    return cards


def main():
    st.set_page_config(page_title='Q4 Flashcards', layout='wide')

    cards = load_cards()
    c = random.choice(cards)

    if st.button('Nieuwe kaart'):
        st.rerun()

    st.subheader(f"Artikel {c['article']}")
    st.info(c['front'])
    st.markdown(f"[Open wet]({c['url']})")

    if 'back' not in st.session_state:
        st.session_state.back = ''

    if not st.session_state.back:
        st.session_state.back = extract(c['url'], c['article'], c['front'])

    st.text_area('Wettekst', st.session_state.back, height=300)


if __name__ == '__main__':
    main()
