def extract(url, article_num):
    try:
        # Stap 1: Haal de BWB-sleutel en het fragment uit de URL
        parsed = urlparse(url)
        fragment = parsed.fragment
        
        # Stap 2: Forceer de 'tekst' weergave en gebruik het fragment als direct doel
        # We voegen de parameter 'xml' toe indien mogelijk, of 'view=text'
        params = parse_qs(parsed.query)
        params['tekst'] = ['1']
        
        # Bouw een schone URL voor de request
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(params, doseq=True),
            '' # Laat fragment leeg voor de server request
        ))

        r = requests.get(clean_url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        # Stap 3: Zoek gericht naar het ID dat in de URL stond (het fragment)
        container = None
        if fragment:
            # Wetten.overheid gebruikt vaak ID's voor artikelen
            container = soup.find(id=fragment)

        # Stap 4: Als ID niet werkt, zoek dan naar de kop met het artikelnummer
        if not container:
            # Zoek een header (h1-h4) of div die begint met "Artikel [nummer]"
            search_pattern = re.compile(rf'^Artikel\s+{re.escape(article_num)}\b', re.I)
            target = soup.find(lambda tag: tag.name in ['h1', 'h2', 'h3', 'div', 'span'] and search_pattern.match(tag.get_text(strip=True)))
            
            if target:
                # Pak de omhullende div van het artikel (vaak class 'cl-content' of 'artikel')
                container = target.find_parent('div', class_=re.compile(r'artikel|cl-content')) or target

        if container:
            return extract_clean_text(container)

        # Stap 5: Fallback - Regex op de volledige platte tekst
        full_text = extract_clean_text(soup)
        # Zoek van "Artikel X" tot het volgende artikel of einde
        match = re.search(rf'(Artikel\s+{re.escape(article_num)}\b.*?)(?=Artikel\s+\d+|$)', full_text, re.S | re.I)
        if match:
            return match.group(1).strip()

    except Exception as e:
        return f"Systeemfout: {str(e)}"

    return 'Artikel niet gevonden. Probeer de herlaad knop.'
