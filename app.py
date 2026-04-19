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
USER_AGENT = 'Mozilla/5.0 (compatible; Q4Flashcards/4.8)'

ARTICLE_RE = re.compile(r'\bArtikel\s*:\s*([^\n]+?)(?=(?:\s+Lid\s*:|\s+Sub\s*:|$))', re.IGNORECASE)
LID_RE = re.compile(r'\bLid\s*:\s*([^\n]+?)(?=(?:\s+Sub\s*:|$))', re.IGNORECASE)

NOISE = {
    'Toon relaties in LiDO','Maak een permanente link','Toon wetstechnische informatie',
    'Gegevens van deze regeling','Vergelijk met andere versies','Bekijk wijzigingsinformatie',
    'Zoek binnen deze regeling','Selecteer een andere versie','Druk het regelingonderdeel af',
    'Sla het regelingonderdeel op','Permalink','...'
}

# 🔴 NIEUW: behoud regeleinden

def norm_text(t):
    t = html.unescape(t or '').replace('\xa0',' ')
    t = t.replace('\r','')
    t = re.sub(r'[ \t]+',' ',t)
    t = re.sub(r'\n{3,}','\n\n',t)
    return t.strip()


def norm_line(t):
    t = html.unescape(t or '').replace('\xa0',' ')
    t = re.sub(r'[ \t]+',' ',t)
    return t.strip()


def tekst_url(url):
    p=urlparse(url); q=parse_qs(p.query); q['tekst']=['1']
    return urlunparse((p.scheme,p.netloc,p.path,p.params,urlencode(q,doseq=True),p.fragment))

# flexibel starten, strikt stoppen

def is_article_start(line, article):
    line = line.strip().lower()
    return line.startswith(f"artikel {article.lower()}")


def is_article_heading(line):
    return bool(re.match(r'^Artikel\s+\d+[a-zA-Z]*\s*$', line.strip()))


def is_lid_start(line,lid=None):
    if lid: return bool(re.match(rf'^{re.escape(lid)}[.:)]\s+',line.strip()))
    return bool(re.match(r'^\d+[.:)]\s+',line.strip()))


def extract_article(lines,article):
    start=None
    for i,l in enumerate(lines):
        if is_article_start(l,article):
            start=i; break
    if start is None: return None

    block=[lines[start]]
    for l in lines[start+1:]:
        if is_article_heading(l): break
        block.append(l)
    return '\n'.join(block).strip()


def extract_lid(text,lid):
    lines=[l.strip() for l in text.split('\n') if l.strip()]
    start=None
    for i,l in enumerate(lines):
        if is_lid_start(l,lid): start=i; break
    if start is None: return None

    block=[lines[start]]
    for l in lines[start+1:]:
        if is_lid_start(l): break
        if is_article_heading(l): break
        block.append(l)
    return '\n'.join(block)


def extract(url,article,lid):
    try:
        r=requests.get(tekst_url(url),timeout=REQUEST_TIMEOUT)
        txt=norm_text(r.text)
        lines=[norm_line(l) for l in txt.split('\n') if norm_line(l)]
        art=extract_article(lines,article)
        if art:
            if lid:
                lidtxt=extract_lid(art,lid)
                if lidtxt: return lidtxt
            return art
    except:
        pass

    # 🔴 fallback HTML
    try:
        r=requests.get(url,timeout=REQUEST_TIMEOUT)
        soup=BeautifulSoup(r.text,'html.parser')
        main=soup.select_one('#content') or soup.select_one('main') or soup.body
        lines=[norm_line(s) for s in main.stripped_strings if norm_line(s)]
        art=extract_article(lines,article)
        if art:
            if lid:
                lidtxt=extract_lid(art,lid)
                if lidtxt: return lidtxt
            return art
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
    if not CACHE_FILE.exists(): return {'cards':[],'errors':[]}
    try: return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except: return {'cards':[],'errors':[]}


def write_cache_payload(payload):
    CACHE_FILE.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')


def load_cards():
    txt=SOURCE_FILE.read_text(encoding='utf-8')
    cards=[]
    for line in txt.splitlines():
        if not line.startswith('* '): continue
        if '→' not in line: continue
        ref=line.split('→')[0].strip()[2:]
        m=re.search(r'\[(.*?)\]\((https?://[^)]+)\)',line)
        if not m: continue
        desc,url=m.group(1),m.group(2)
        am=ARTICLE_RE.search(ref)
        if not am: continue
        article=am.group(1)
        lm=LID_RE.search(ref)
        lid=lm.group(1) if lm else None
        law=ref.split(' Artikel:')[0]
        label=f"{law}, artikel {article}"+(f", lid {lid}" if lid else "")
        cards.append(dict(law=law,article=article,lid=lid,reference=ref,front=desc,url=url,label=label))

    payload=read_cache_payload()
    for c in cards:
        for pc in payload.get('cards',[]):
            if pc['reference']==c['reference']:
                c['back']=pc.get('back')

    return cards


def get_back(card):
    if card.get('back'): return card['back']
    t=extract(card['url'],card['article'],card['lid'])
    persist(card,t); card['back']=t
    return t


def reload_card():
    c=st.session_state.get('current_card')
    if not c: return
    t=extract(c['url'],c['article'],c['lid'])
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