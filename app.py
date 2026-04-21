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
ONDER_RE = re.compile(r'\bonder\s+([A-Za-z0-9,\s]+)', re.I)

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

def extract_requested_onderdelen(source_text):
    m = ONDER_RE.search(source_text or '')
    if not m:
        return []
    raw = m.group(1)
    parts = re.split(r'\s*,\s*|\s+en\s+', raw, flags=re.I)
    found = []
    for part in parts:
        part = normalize(part).strip(' .;:')
        if re.fullmatch(r'[A-Za-z0-9]+', part or ''):
            found.append(part.lower())
    return found

def line_starts_lid(line, wanted_lid):
    line = normalize(line)
    return bool(re.match(rf'^{re.escape(str(wanted_lid))}[.:)]?\b', line))

def line_starts_new_lid(line):
    line = normalize(line)
    return bool(re.match(r'^\d+[.:)]?\b', line))

def line_starts_letter(line):
    line = normalize(line)
    m = re.match(r'^([a-z])[.:)]?\b', line, re.I)
    return m.group(1).lower() if m else None

def line_starts_subnumber(line):
    line = normalize(line)
    return bool(re.match(r'^\d+[°o]?[.:)]?\b', line))

def extract_onderdelen_from_lid_lines(lid_lines, wanted_onderdelen):
    if not wanted_onderdelen:
        return '\n'.join(lid_lines)

    wanted_onderdelen = [o.lower() for o in wanted_onderdelen]
    result = []
    current_letter = None
    current_chunk = []
    collected_any = False

    def flush_chunk():
        nonlocal current_letter, current_chunk, collected_any, result
        if current_letter and current_chunk and current_letter.lower() in wanted_onderdelen:
            result.extend(current_chunk)
            collected_any = True
        current_chunk = []

    for line in lid_lines[1:]:
        letter = line_starts_letter(line)
        if letter:
            flush_chunk()
            current_letter = letter
            current_chunk = [line]
        elif current_letter:
            current_chunk.append(line)
        elif not collected_any:
            result.append(line)

    flush_chunk()
    return '\n'.join(result) if result else '\n'.join(lid_lines)

def extract_lid_and_onderdelen(block_lines, wanted_lid, wanted_onderdelen):
    if not block_lines:
        return ''

    if not wanted_lid:
        return '\n'.join(block_lines)

    lid_lines = []
    capture_lid = False

    for line in block_lines:
        if line_starts_lid(line, wanted_lid):
            capture_lid = True
            lid_lines.append(line)
            continue

        if capture_lid and line_starts_new_lid(line):
            break

        if capture_lid:
            lid_lines.append(line)

    if lid_lines:
        if wanted_onderdelen:
            return extract_onderdelen_from_lid_lines(lid_lines, wanted_onderdelen)
        return '\n'.join(lid_lines)

    return '\n'.join(block_lines)

def extract_structured_article_text(soup, article, source_text):
    wanted_lid_match = LID_RE.search(source_text or '')
    wanted_lid = wanted_lid_match.group(1) if wanted_lid_match else None
    wanted_onderdelen = extract_requested_onderdelen(source_text)

    article_header = None
    for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'div', 'span', 'p']):
        text = normalize(tag.get_text(' ', strip=True))
        parsed = parse_article(text)
        if parsed and article_matches(parsed[0], article):
            article_header = tag
            break

    if not article_header:
        return ''

    holder = article_header.parent
    while holder and holder.name not in ['section', 'article', 'div', 'main', 'body']:
        holder = holder.parent
    if not holder:
        holder = article_header.parent or soup

    if wanted_lid:
        lid_node = None
        for tag in holder.find_all(['li', 'p', 'div'], recursive=True):
            text = normalize(tag.get_text(' ', strip=True))
            if line_starts_lid(text, wanted_lid):
                lid_node = tag
                break

        if lid_node:
            if wanted_onderdelen:
                collected = [str(wanted_lid)]
                for child in lid_node.find_all(['li', 'p', 'div'], recursive=True):
                    text = normalize(child.get_text(' ', strip=True))
                    letter = line_starts_letter(text)
                    if letter and letter in wanted_onderdelen:
                        collected.append(text)
                if len(collected) > 1:
                    return '\n'.join(collected)

            text = normalize(lid_node.get_text('\n', strip=True))
            if text:
                return text

    return ''

def extract(url, article, source_text):
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, 'html.parser')

        structured = extract_structured_article_text(soup, article, source_text)
        if structured:
            return structured

        lines = page_lines(r.text)
        block = extract_article(lines, article)

        if block:
            lid_match = LID_RE.search(source_text or '')
            lid = lid_match.group(1) if lid_match else None
            onderdelen = extract_requested_onderdelen(source_text)
            return extract_lid_and_onderdelen(block, lid, onderdelen)

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
    if 'expander_nonce' not in st.session_state:
        st.session_state.expander_nonce = 0

    if st.button('Nieuwe kaart'):
        st.session_state.card = random.choice(cards)
        st.session_state.back = ''
        st.session_state.expander_nonce += 1
        st.rerun()

    c = st.session_state.card

    st.subheader(c['title'])
    st.info(c['front'])
    st.markdown(f"[Open wet]({c['url']})")

    if not st.session_state.back:
        st.session_state.back = extract(c['url'], c['article'], c['source_text'])

    with st.expander('Antwoord', expanded=False):
        st.text_area('Wettekst', st.session_state.back, height=300, key=f"wettekst_{st.session_state.expander_nonce}")

if __name__ == '__main__':
    main()
