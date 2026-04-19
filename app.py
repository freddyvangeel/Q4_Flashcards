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
ALL_LAWS_LABEL = 'Alle wetten'
REQUEST_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/5.3)'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE = {
    'Toon relaties in LiDO','Maak een permanente link','Toon wetstechnische informatie',
    'Gegevens van deze regeling','Vergelijk met andere versies','Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling','Selecteer een andere versie','Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op','Permalink','...'
}

# 🔴 FIX: geen onnatuurlijke regeleinden meer

def extract_clean_text(container):
    raw = container.get_text(" ")
    text = html.unescape(raw).replace('\xa0',' ')
    text = re.sub(r'\s+', ' ', text)

    # leden structureren
    text = re.sub(r'(?<!\d)(\b\d+\b)\s+', r'\n\1 ', text)
    text = re.sub(r'\s([a-z]\.)\s+', r'\n\1 ', text)

    return text.strip()


def tekst_url(url: str) -> str:
    p=urlparse(url); q=parse_qs(p.query); q['tekst']=['1']
    return urlunparse((p.scheme,p.netloc,p.path,p.params,urlencode(q,doseq=True),p.fragment))


def find_article_container(soup, article):
    article = article.lower()
    pattern = re.compile(rf'^artikel\s+{re.escape(article)}', re.I)

    for node in soup.find_all(['h1','h2','h3','div','span','strong']):
        txt = node.get_text(" ", strip=True).lower()
        if pattern.match(txt):
            return node.find_parent(['article','section','div']) or node

    return None


def extract(url, article, lid):
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, 'html.parser')

        container = find_article_container(soup, article)
        if not container:
            return 'Artikel niet gevonden'

        text = extract_clean_text(container)

        # knip op volgend artikel
        parts = re.split(r'(?=Artikel \d+[a-zA-Z]*)', text)
        for part in parts:
            if part.lower().startswith(f"artikel {article.lower()}"):
                return part.strip()

    except:
        pass

    return 'Artikel niet gevonden'


def persist(card,text):
    p=read_cache_payload(); cards=p.get('cards',[])
    for c in cards:
        if c['reference']==card['reference']:
            c['back']=text; break
    else:
        nc=dict(card); nc['back']=text; cards.append(nc)
    p['cards']=cards; write_cache_payload(p)


def read_cache_payload():
    if not CACHE_FILE.exists(): return {'cards':[]}
    try: return json.loads(CACHE_FILE.read_text())
    except: return {'cards':[]}


def write_cache_payload(p):
    CACHE_FILE.write_text(json.dumps(p,indent=2,ensure_ascii=False))


def load_cards():
    txt=SOURCE_FILE.read_text()
    cards=[]
    for l in txt.splitlines():
        if not l.startswith('* ') or '→' not in l: continue
        ref=l.split('→')[0][2:].strip()
        m=re.search(r'\[(.*?)\]\((https?://[^)]+)\)',l)
        if not m: continue
        desc,url=m.group(1),m.group(2)
        am=ARTICLE_RE.search(ref)
        if not am: continue
        article=am.group(1)
        law=ref.split(' Artikel:')[0]
        cards.append(dict(reference=ref,front=desc,url=url,article=article,law=law,label=f"{law}, artikel {article}"))

    payload=read_cache_payload()
    for c in cards:
        for pc in payload.get('cards',[]):
            if pc['reference']==c['reference']:
                c['back']=pc.get('back')

    return cards


def get_back(card):
    if card.get('back'): return card['back']
    t=extract(card['url'],card['article'],None)
    persist(card,t); card['back']=t
    return t


def reload_card():
    c=st.session_state.get('current_card')
    if not c: return
    t=extract(c['url'],c['article'],None)
    persist(c,t)
    st.session_state.current_card['back']=t
    st.session_state.back_text=t


def main():
    st.title('Q4 flashcards')

    cards=load_cards()
    laws=sorted({c['law'] for c in cards})
    sel=st.multiselect('Filter op wet',[ALL_LAWS_LABEL]+laws,default=[ALL_LAWS_LABEL])
    if ALL_LAWS_LABEL not in sel:
        cards=[c for c in cards if c['law'] in sel]

    if 'current_card' not in st.session_state:
        st.session_state.current_card=random.choice(cards)
        st.session_state.back_text=get_back(st.session_state.current_card)

    col1,col2=st.columns(2)
    with col1:
        if st.button('Nieuwe kaart'):
            st.session_state.current_card=random.choice(cards)
            st.session_state.back_text=get_back(st.session_state.current_card)
    with col2:
        if st.button('Herlaad wet'):
            reload_card()

    c=st.session_state.current_card
    st.subheader(c['label'])

    st.markdown(f'<a href="{c["url"]}" target="_blank">{c["front"]}</a>', unsafe_allow_html=True)

    with st.expander('Achterkant'):
        st.text_area('Wettekst',st.session_state.back_text,height=420)

if __name__=='__main__': main()