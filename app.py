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
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
REQUEST_TIMEOUT = 20

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)
ARTICLE_NUM_PATTERN = r'\d+(?::\d+)?[a-zA-Z]*'

NOISE_PHRASES = [
    'Toon relaties in LiDO','Maak een permanente link','Toon wetstechnische informatie',
    'Gegevens van deze regeling','Vergelijk met andere versies','Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling','Selecteer een andere versie',
    'Druk het regelingonderdeel af','Sla het regelingonderdeel op'
]

HEADER_PATTERNS = [
    re.compile(r'^hoofdstuk', re.I),
    re.compile(r'^titeldeel', re.I),
    re.compile(r'^afdeling', re.I),
    re.compile(r'^paragraaf', re.I),
]


def normalize(t):
    return re.sub(r'\s+', ' ', html.unescape(t or '').replace('\xa0',' ')).strip()


def is_noise(line):
    return not line or line in NOISE_PHRASES or line == '...'


def is_header(line):
    return any(p.match(line) for p in HEADER_PATTERNS)


def parse_article(line):
    m = re.match(rf'^artikel\s+({ARTICLE_NUM_PATTERN})(.*)$', line, re.I)
    if not m:
        return None
    return m.group(1).lower(), normalize(m.group(2))


def page_lines(html_text):
    soup = BeautifulSoup(html_text, 'html.parser')
    txt = soup.select_one('#content') or soup.body or soup
    lines = []
    for l in txt.get_text('\n').splitlines():
        l = normalize(l)
        if not is_noise(l):
            lines.append(l)
    return lines


def extract_article(lines, article):
    key = article.lower()
    block = []
    started = False

    for line in lines:
        parsed = parse_article(line)

        if parsed and parsed[0] == key:
            started = True
            block.append(f'Artikel {article}')
            if parsed[1]:
                block.append(parsed[1])
            continue

        if not started:
            continue

        if parse_article(line) or is_header(line):
            break

        block.append(line)

    return '\n'.join(block) if len(block) > 2 else None


def extract(url, article, lid=None):
    try:
        r = requests.get(url, headers={'User-Agent':USER_AGENT}, timeout=REQUEST_TIMEOUT)
        lines = page_lines(r.text)
        txt = extract_article(lines, article)
        if txt:
            return txt
    except:
        pass
    return 'Artikel tekst niet gevonden op pagina.'


def main():
    st.set_page_config(layout='wide')

    if not SOURCE_FILE.exists():
        st.error('Bronbestand ontbreekt')
        return

    cards = []
    for line in SOURCE_FILE.read_text(encoding='utf-8').splitlines():
        if '→' not in line:
            continue
        m = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', line)
        if not m:
            continue
        article = ARTICLE_RE.search(line)
        if not article:
            continue
        cards.append({
            'article': article.group(1).strip(),
            'url': m.group(2),
            'front': m.group(1)
        })

    c = random.choice(cards)

    if st.button('Volgende'):
        st.rerun()

    if st.button('Herlaad'):
        st.session_state['back'] = ''

    st.subheader(f"Artikel {c['article']}")
    st.info(c['front'])

    if 'back' not in st.session_state or not st.session_state['back']:
        st.session_state['back'] = extract(c['url'], c['article'])

    st.text_area('Wettekst', st.session_state['back'], height=300)

if __name__ == '__main__':
    main()
