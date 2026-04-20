import html
import json
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# --- Configuratie ---
CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
SOURCE_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def extract_clean_text(container):
    if not container: return ""
    raw = container.get_text(separator=" ", strip=True)
    text = html.unescape(raw).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(?<!\d)(\d+\.)\s+', r'\n\1 ', text)
    return text.strip()

def extract(url, article_num):
    try:
        p = urlparse(url)
        q = parse_qs(p.query); q['tekst'] = ['1']
        fetch_url = urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), ''))
        
        r = requests.get(fetch_url, headers={'User-Agent': USER_AGENT}, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        # 1. Zoek het anker/ID uit de URL fragment
        container = None
        if p.fragment:
            container = soup.find(id=p.fragment)

        # 2. Als ID niet werkt of alleen de kop bevat, zoek via de tekst
        if not container or len(container.get_text(strip=True)) < 20:
            pattern = re.compile(rf'^Artikel\s+{re.escape(article_num)}\b', re.I)
            # Zoek de specifieke kop
            target = soup.find(lambda tag: tag.name in ['h1','h2','h3','div','span'] and pattern.match(tag.get_text(strip=True)))
            
            if target:
                # Probeer de parent-container te pakken die de tekst bevat (vaak class 'cl-content')
                container = target.find_parent('div', class_=re.compile(r'artikel|cl-content|sectie'))
                
                # Als dat niet lukt, pakken we de kop en alle broertjes (siblings) daarna
                if not container:
                    content_parts = [target.get_text(strip=True)]
                    for sibling in target.find_next_siblings():
                        # Stop als we het volgende artikel tegenkomen
                        if sibling.name in ['h1','h2','h3'] or "Artikel" in sibling.get_text()[:15]:
                            break
                        content_parts.append(sibling.get_text(separator=" ", strip=True))
                    return "\n".join(content_parts)

        if container:
            return extract_clean_text(container)
        
        # 3. Laatste redding: Regex op de volledige platte tekst van de pagina
        full_text = extract_clean_text(soup)
        match = re.search(rf'(Artikel\s+{re.escape(article_num)}\b.*?)(?=Artikel\s+\d+|$)', full_text, re.S | re.I)
        if match:
            return match.group(1).strip()
            
    except Exception as e:
        return f"Fout bij ophalen: {str(e)}"

    return "Artikel tekst niet gevonden op pagina."

def load_cards():
    if not SOURCE_FILE.exists():
        return []
    cards = []
    try:
        content = SOURCE_FILE.read_text(encoding='utf-8')
        for line in content.splitlines():
            if '→' not in line: continue
            parts = line.split('→')
            front_text = parts[0].replace('*', '').strip()
            
            link_match = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', parts[1])
            if not link_match: continue
            
            desc, url = link_match.group(1), link_match.group(2)
            art_match = re.search(r'Artikel\s*:\s*([^\s,]+)', front_text, re.I)
            article = art_match.group(1) if art_match else ""
            law = front_text.split('Artikel:')[0].strip().rstrip(',')

            cards.append({
                'id': f"{law}_{article}_{desc}"[:50],
                'law': law, 'article': article, 'front': desc, 'url': url,
                'label': f"{law} - Art. {article}"
            })
    except:
        st.error("Fout bij lezen bronbestand.")
    return cards

def main():
    st.set_page_config(page_title="Q4 Flashcards", layout="wide")
    
    cards = load_cards()
    if not cards:
        st.error(f"Bestand {SOURCE_FILE.name} is leeg of ontbreekt.")
        return

    # Filter
    laws = sorted({c['law'] for c in cards})
    sel = st.sidebar.multiselect('Wetten', ['Alle'] + laws, default=['Alle'])
    filtered = cards if 'Alle' in sel else [c for c in cards if c['law'] in sel]

    if not filtered:
        st.warning("Geon kaarten voor deze selectie.")
        return

    # Session State (Veilig)
    if 'card' not in st.session_state or st.session_state.card not in [c['id'] for c in filtered]:
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = ""

    c = st.session_state.card_obj

    # Knoppen
    col1, col2 = st.columns(2)
    if col1.button('Volgende 🎲'):
        st.session_state.card_obj = random.choice(filtered)
        st.session_state.card = st.session_state.card_obj['id']
        st.session_state.back = ""
        st.rerun()
    
    if col2.button('Herlaad 🔄'):
        st.session_state.back = extract(c['url'], c['article'])
        st.rerun()

    # Content
    st.divider()
    st.subheader(c['label'])
    st.info(c['front'])
    st.caption(f"[Link naar wet]({c['url']})")

    if not st.session_state.back:
        with st.spinner("Laden..."):
            st.session_state.back = extract(c['url'], c['article'])

    with st.expander("Antwoord", expanded=False):
        st.text_area("Wettekst", st.session_state.back, height=300)

if __name__ == '__main__':
    main()
