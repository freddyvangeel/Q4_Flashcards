import html
import json
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# Configuratie
CACHE_FILE = Path(__file__).with_name('flashcards_cache.json')
SOURCE_FILE = Path(__file__).with_name('Juridisch kader Q1 tm Q5.md')
ALL_LAWS_LABEL = 'Alle wetten'
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

ARTICLE_RE = re.compile(r'Artikel\s*:\s*([^\n]+)', re.IGNORECASE)

NOISE_PHRASES = [
    "Toon relaties in LiDO", "Maak een permanente link", "Toon wetstechnische informatie",
    "Gegevens van deze regeling", "Vergelijk met andere versies", "Bekijk wijzigingsinformatie",
    "Zoek binnen deze regeling", "Selecteer een andere versie", "Druk het regelingonderdeel af",
    "Sla het regelingonderdeel op", "Inhoudsopgave", "Kenmerken"
]

def extract_clean_text(container):
    """Schoont de HTML container op naar leesbare tekst."""
    if not container:
        return ""
    
    # Verwijder script en style elementen
    for s in container(["script", "style"]):
        s.decompose()

    raw = container.get_text(separator=" ", strip=True)
    text = html.unescape(raw).replace('\xa0', ' ')

    for phrase in NOISE_PHRASES:
        text = text.replace(phrase, "")

    # Opschonen witruimte
    text = re.sub(r'\s+', ' ', text)
    # Leden op nieuwe regels zetten (cijfer gevolgd door punt aan begin van zin)
    text = re.sub(r'(?<!\d)(\d+\.)\s+', r'\n\1 ', text)
    # Subleden (letters gevolgd door punt)
    text = re.sub(r'\s([a-z]\.)\s+', r'\n\1 ', text)

    return text.strip()

def tekst_url(url: str) -> str:
    """Forceert de 'tekst=1' weergave voor minder HTML-ruis."""
    p = urlparse(url)
    q = parse_qs(p.query)
    q['tekst'] = ['1']
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment))

def extract(url, article_num):
    """Haalt de wettekst op basis van URL fragment of artikelnummer."""
    try:
        f_url = tekst_url(url)
        r = requests.get(f_url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        # Strategie 1: Zoek op ID uit URL fragment
        fragment = urlparse(url).fragment
        container = None
        if fragment:
            container = soup.find(id=fragment)

        # Strategie 2: Zoek op tekstmatch indien ID niet werkt
        if not container:
            search_re = re.compile(rf'^Artikel\s+{re.escape(article_num)}', re.I)
            # Zoek in headers die vaak het artikelnummer bevatten
            header = soup.find(['h1', 'h2', 'h3', 'span', 'div'], string=search_re)
            if header:
                container = header.find_parent(['div', 'article']) or header

        if container:
            return extract_clean_text(container)
            
    except Exception as e:
        return f"Fout bij ophalen: {str(e)}"

    return 'Artikel niet gevonden op de pagina.'

def read_cache():
    if not CACHE_FILE.exists(): return {}
    try: return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except: return {}

def write_cache(data):
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

def load_cards():
    if not SOURCE_FILE.exists():
        st.error(f"Bestand {SOURCE_FILE.name} niet gevonden.")
        return []
        
    txt = SOURCE_FILE.read_text(encoding='utf-8')
    cards = []
    cache = read_cache()

    for line in txt.splitlines():
        if not line.startswith('* ') or '→' not in line: continue
        
        # Split op pijl: voorkant → [Link](URL)
        parts = line.split('→')
        ref_part = parts[0][2:].strip() # Alles voor de pijl
        link_part = parts[1].strip()
        
        m_link = re.search(r'\[(.*?)\]\((https?://[^)]+)\)', link_part)
        if not m_link: continue
        
        desc, url = m_link.group(1), m_link.group(2)
        
        m_art = ARTICLE_RE.search(ref_part)
        article = m_art.group(1).strip() if m_art else ""
        law = ref_part.split('Artikel:')[0].strip().rstrip(',')

        card_id = f"{law}_{article}_{desc}"
        
        cards.append({
            'id': card_id,
            'law': law,
            'article': article,
            'front': desc,
            'url': url,
            'label': f"{law} - Art. {article}",
            'back': cache.get(card_id)
        })
    return cards

def main():
    st.set_page_config(page_title="Q4 Flashcards", layout="wide")
    st.title('Q4 Juridische flashcards')

    all_cards = load_cards()
    if not all_cards:
        st.warning("Geen kaarten geladen. Controleer het bronbestand.")
        return

    # Sidebar filters
    laws = sorted({c['law'] for c in all_cards})
    sel = st.sidebar.multiselect('Filter op wet', [ALL_LAWS_LABEL] + laws, default=[ALL_LAWS_LABEL])
    
    filtered_cards = all_cards
    if ALL_LAWS_LABEL not in sel:
        filtered_cards = [c for c in all_cards if c['law'] in sel]

    # Session state initialisatie
    if 'current_card' not in st.session_state or st.session_state.current_card['id'] not in [c['id'] for c in filtered_cards]:
        st.session_state.current_card = random.choice(filtered_cards)

    # Actie knoppen
    col1, col2 = st.columns(2)
    with col1:
        if st.button('Volgende kaart 🎲'):
            st.session_state.current_card = random.choice(filtered_cards)
            st.rerun()
    with col2:
        if st.button('Forceer herladen 🔄'):
            card = st.session_state.current_card
            text = extract(card['url'], card['article'])
            cache = read_cache()
            cache[card['id']] = text
            write_cache(cache)
            st.session_state.current_card['back'] = text
            st.rerun()

    # Weergave kaart
    card = st.session_state.current_card
    st.divider()
    st.subheader(card['label'])
    st.info(f"**Vraag:** {card['front']}")
    st.caption(f"[Open originele bron]({card['url']})")

    # Achterkant ophalen indien leeg
    if not card.get('back'):
        with st.spinner('Wettekst ophalen...'):
            text = extract(card['url'], card['article'])
            cache = read_cache()
            cache[card['id']] = text
            write_cache(cache)
            card['back'] = text

    with st.expander("Toon antwoord", expanded=False):
        st.text_area("Wettekst", card['back'], height=400)

if __name__ == '__main__':
    main()
