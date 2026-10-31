#!/usr/bin/env python3
"""Volantini di Ivrea: legge i siti dei negozi e scrive docs/index.html e docs/dati.json.

Usa solo la libreria standard, più poppler (pdftotext, pdftohtml, pdftoppm).
I prodotti con foto e prezzo vengono da tre strade diverse, spiegate in CONTEXT.md:
il sito Carrefour, i ritagli di DoveConviene per Bennet, i PDF per Conad e Coop (ritagli.py).

Se un negozio non si legge, tiene i dati dell'ultima volta e lo segnala sulla pagina;
in quel caso esce con codice 3, così GitHub Actions lo segnala per mail.
Le scelte e i perché sono in CONTEXT.md.
"""
import csv
import datetime as dt
import html
import io
import json
import re
import subprocess
import sys
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import categorie  # noqa: E402
import ritagli  # noqa: E402

ROMA = ZoneInfo("Europe/Rome")
CARTELLA = Path(__file__).resolve().parent
USCITA = CARTELLA / "docs"
MODELLO = CARTELLA / "modello.html"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

NEGOZI = [
    {"id": "bennet", "nome": "Bennet", "dove": "via Dora Baltea 31", "lettore": "bennet",
     "url": "https://www.doveconviene.it/ivrea/volantino/bennet", "fonte": "DoveConviene"},
    {"id": "conad", "nome": "Conad", "dove": "corso Vercelli 131", "lettore": "conad",
     "url": "https://www.conad.it/ricerca-negozi/conad-corso-vercelli-131-10015-ivrea--008936",
     "fonte": "sito Conad"},
    {"id": "conad-city", "nome": "Conad City", "dove": "viale Liberazione 1", "lettore": "conad",
     "url": "https://www.conad.it/ricerca-negozi/conad-city-viale-della-liberazione-1-10015-ivrea--003791",
     "fonte": "sito Conad"},
    {"id": "coop", "nome": "Coop", "dove": "corso Vercelli", "lettore": "coop",
     "url": "https://negozi.volantinopiu.com/ccno-8001120619099.html",
     "fonte": "sito Coop"},
    {"id": "carrefour-market", "nome": "Carrefour Market", "dove": "via Circonvallazione 54", "lettore": "carrefour",
     "url": "https://www.carrefour.it/volantino/supermercato-carrefour-market-ivrea-via-circonvallazione-54/5158",
     "fonte": "sito Carrefour"},
    {"id": "carrefour-iper", "nome": "Carrefour Iper", "dove": "Burolo, via Liguria 1", "lettore": "carrefour",
     "url": "https://www.carrefour.it/volantino/ipermercato-carrefour-iper-burolo-via-liguria-n-1/0752",
     "fonte": "sito Carrefour"},
]

# Quello che ho letto a mano nei volantini. Ogni voce sparisce da sola quando il volantino
# non c'è più: la chiave è il file o il numero del volantino. Il testo è verificato sulla pagina.
NOTE_A_MANO = {
    "29336": [  # Coop, Offerte Top, 29/10-11/11
        {"dal": "2026-10-29", "al": "2026-11-04",
         "testo": "Frutta e verdura, 1ª settimana: banane 1,28 €/kg, zucchine 1,48 €/kg, verza 0,98 €/kg, clementine −25% ai soci (pag. 3)"},
        {"dal": "2026-11-05", "al": "2026-11-11",
         "testo": "Frutta e verdura, 2ª settimana: finocchi 1,68 €/kg, pere Abate 2,48 €/kg, cavolo nero 1,78 €/kg, kiwi gialli 2,98 € i 500 g (pag. 3)"},
        {"dal": "2026-11-05", "al": "2026-11-18",
         "testo": "Scegli tu: sconti del 30, 40 e 50% sulle grandi marche (da pag. 24)"},
        {"dal": "2026-11-05", "al": "2026-12-24",
         "testo": "Aspettando il Natale: addobbi e alberi (pagg. 20-22)"},
    ],
    "20262623pconadpiemonte": [
        {"dal": "2026-11-05", "al": "2026-11-14",
         "testo": "In copertina olio Monini classico 1 L a 4,59 €, pizza Buitoni Bella Napoli (2 pezzi) a 2,79 €, detersivo Dixan (4 confezioni) a 8,90 €. Pezzi limitati"},
    ],
    "20262623pcitypiemonte": [
        {"dal": "2026-11-05", "al": "2026-11-14",
         "testo": "Dentro c'è l'olio Monini classico 1 L a 4,59 €. Pezzi limitati"},
    ],
}

# Volantini che non sono "il" volantino del negozio: stanno sotto, in grigio.
PAROLE_CATALOGO = ("premio", "perché conviene", "catalogo", "ceste", "speciale", "punti",
                   "addobb", "giocattol", "vini", "payback")


class NonLetto(Exception):
    pass


def scarica(url, timeout=40):
    richiesta = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    ultimo = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
                return risposta.read()
        except Exception as errore:  # la rete sbaglia: un secondo tentativo, poi basta
            ultimo = errore
    raise NonLetto(f"{url}: {ultimo}")


def testo(url):
    return scarica(url).decode("utf-8", "replace")


def tipo_di(titolo):
    return "catalogo" if any(p in titolo.lower() for p in PAROLE_CATALOGO) else "principale"


def accenti(titolo):
    return re.sub(r"([aeiou])'(?=\W|$)", lambda m: "àèìòù"["aeiou".index(m.group(1))], titolo)


def data_vicina(giorno, mese, oggi):
    """Le date senza anno: l'anno che la mette più vicina a oggi."""
    candidate = [dt.date(oggi.year + delta, mese, giorno) for delta in (-1, 0, 1)]
    return min(candidate, key=lambda d: abs((d - oggi).days))


# --- Bennet: il suo sito e PromoQui non rispondono al giro automatico (403). DoveConviene sì.

BASE_BENNET = "https://www.doveconviene.it/ivrea/iper-e-super/bennet/volantino/ultime-offerte-bennet?flyerId="


def blocchi_json_ld(pagina):
    for blocco in re.finditer(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', pagina, re.S):
        try:
            yield json.loads(blocco.group(1))
        except ValueError:
            continue


def leggi_bennet(negozio, oggi):
    """La pagina della città elenca i volantini; quella del volantino ha le date e, nei prodotti, il titolo."""
    lista = testo(negozio["url"])
    risultato = []
    for numero in sorted(set(re.findall(r"/bennet/volantino/ultime-offerte-bennet\?flyerId=(\d+)", lista))):
        dati = list(blocchi_json_ld(testo(BASE_BENNET + numero)))
        date = next((d for d in dati if d.get("datePublished") and d.get("expires")), None)
        if not date:
            raise NonLetto(f"Bennet {numero}: date non trovate")
        titolo = next((d["description"] for d in dati if d.get("@type") == "Product" and d.get("description")), "Volantino")
        risultato.append({
            "chiave": numero,
            "titolo": accenti(html.unescape(titolo).strip()),
            "dal": date["datePublished"][:10],
            "al": date["expires"][:10],
            "url": BASE_BENNET + numero,
        })
    return risultato


# --- Conad: la scheda del negozio contiene anche i volantini della settimana dopo

def titolo_conad(grezzo):
    titolo = re.sub(r"\b(SPAZIO|SUPERSTORE|CONAD|CITY|PIEMONTE|LIGURIA)\b", " ", grezzo.upper())
    titolo = re.sub(r"[\s-]+", " ", titolo).strip().capitalize()
    return titolo.replace("Mi premio", "miPremio")


def leggi_conad(negozio, oggi):
    pagina = html.unescape(testo(negozio["url"]))
    decoder = json.JSONDecoder()
    visti = {}
    for inizio in re.finditer(r'\{"name":"[^"]+\.pdf","pdfPath"', pagina):
        try:
            voce, _ = decoder.raw_decode(pagina[inizio.start():])
        except ValueError:
            continue
        if voce.get("visible") is False or not voce.get("validFrom") or not voce.get("validTo"):
            continue
        visti[voce.get("slug")] = voce

    def giorno(millisecondi):
        return dt.datetime.fromtimestamp(millisecondi / 1000, ROMA).date()

    risultato = []
    for voce in visti.values():
        al = giorno(voce["validTo"])
        visibile_fino = giorno(voce["visibleTo"]) if voce.get("visibleTo") else al
        elemento = {
            "chiave": voce["name"].rsplit(".", 1)[0],
            "titolo": titolo_conad(voce.get("feTitle") or voce.get("title") or voce["name"]),
            "dal": giorno(voce["validFrom"]).isoformat(),
            "al": al.isoformat(),
            "url": voce.get("pdfUrl") or (voce.get("link") or {}).get("href"),
            "pdf": voce.get("pdfUrl"),
        }
        # Sottocosto 5-14/11: la copertina dice «altre offerte fino al 18/11», cioè visibleTo.
        if visibile_fino > al:
            elemento["al_extra"] = visibile_fino.isoformat()
        risultato.append(elemento)
    return risultato


# --- Carrefour: il menu dei volantini nella pagina del punto vendita

def leggi_carrefour(negozio, oggi):
    pagina = testo(negozio["url"])
    risultato = {}
    for trovato in re.finditer(r'href="(/volantino/[^"]+/\d+)"[^>]*>(.*?)</a>', pagina, re.S):
        scritto = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", trovato.group(2)))).strip()
        date = re.match(r"dal (\d{1,2})/(\d{1,2}) al (\d{1,2})/(\d{1,2}) (.+)", scritto)
        if not date:
            continue
        al = data_vicina(int(date.group(3)), int(date.group(4)), oggi)
        dal = data_vicina(int(date.group(1)), int(date.group(2)), oggi)
        if dal > al:
            dal = dt.date(dal.year - 1, dal.month, dal.day)
        chiave = trovato.group(1).rsplit("/", 1)[1]
        risultato[chiave] = {
            "chiave": chiave,
            "titolo": date.group(5).strip(),
            "dal": dal.isoformat(),
            "al": al.isoformat(),
            "url": "https://www.carrefour.it" + trovato.group(1),
        }
    return list(risultato.values())


# --- Coop: dal sito Coop il volantino del negozio; nel PDF le date e le pagine che partono dopo

MESI = {m: i + 1 for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}


def pagine_con_date(percorso_pdf):
    """Cerca nelle pagine «Prezzi validi dal 5 al 18 novembre» e «DAL 5 ALL'11 NOVEMBRE»."""
    uscita = subprocess.run(["pdftotext", "-raw", str(percorso_pdf), "-"],
                            capture_output=True, timeout=180)
    if uscita.returncode != 0:
        return {}
    finestre = {}
    schema = re.compile(
        r"dal\s+(\d{1,2})(?:\s+([a-zà-ù]+))?\s+all?['’\s]\s*(\d{1,2})\s+([a-zà-ù]+)", re.I)
    for numero, pagina in enumerate(uscita.stdout.decode("utf-8", "replace").split("\f"), start=1):
        for gi, mi, gf, mf in schema.findall(pagina):
            mese_fine = MESI.get(mf.lower())
            mese_inizio = MESI.get(mi.lower()) if mi else mese_fine
            if mese_fine and mese_inizio:
                finestre.setdefault((mese_inizio, int(gi), mese_fine, int(gf)), set()).add(numero)
    return finestre


def leggi_coop(negozio, oggi):
    """La pagina del negozio dà titolo e volantino; le date sono scritte nel PDF. Letti una volta sola per volantino."""
    pagina = testo(negozio["url"])
    risultato = []
    for trovato in re.finditer(r"https://negozi\.volantinopiu\.com/redirect(\d+)\.html\?id_pv=\d+", pagina):
        chiave = trovato.group(1)
        if any(v["chiave"] == chiave for v in risultato):
            continue
        memoria = USCITA / "img" / chiave / "volantino.json"
        if memoria.exists():
            risultato.append(json.loads(memoria.read_text("utf-8")))
            continue
        titoli = re.findall(r"<h5[^>]*>\s*([^<]+?)\s*</h5>", pagina[:trovato.start()])
        richiesta = urllib.request.Request(trovato.group(0), headers={"User-Agent": UA})
        with urllib.request.urlopen(richiesta, timeout=40) as risposta:
            url_volantino = risposta.geturl()
            interna = risposta.read().decode("utf-8", "replace")
        pdf = re.search(r"https://resources\.volantinopiu\.it/flyer/[^\"' ?]+\.pdf", interna)
        if not pdf:
            raise NonLetto(f"Coop {chiave}: PDF non trovato")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as file_pdf:
            file_pdf.write(scarica(pdf.group(0), timeout=180))
            file_pdf.flush()
            finestre = pagine_con_date(file_pdf.name)
        if not finestre:
            raise NonLetto(f"Coop {chiave}: date non trovate nel PDF")
        # Le date del volantino sono quelle scritte sul maggior numero di pagine
        principale = max(finestre, key=lambda k: len(finestre[k]))
        dal = data_vicina(principale[1], principale[0], oggi)
        al = data_vicina(principale[3], principale[2], oggi)
        note = []
        for (mese_i, giorno_i, mese_f, giorno_f), pagine in finestre.items():
            inizio, fine = data_vicina(giorno_i, mese_i, oggi), data_vicina(giorno_f, mese_f, oggi)
            if inizio > dal and fine >= inizio:
                elenco = ", ".join(str(n) for n in sorted(pagine))
                note.append({"dal": inizio.isoformat(), "al": fine.isoformat(), "testo": f"Offerte che partono dopo: pag. {elenco}"})
        volantino = {
            "chiave": chiave,
            "titolo": titoli[-1] if titoli else "Volantino",
            "dal": dal.isoformat(),
            "al": al.isoformat(),
            "url": url_volantino,
            "pdf": pdf.group(0),
            "note": note,
        }
        memoria.parent.mkdir(parents=True, exist_ok=True)
        memoria.write_text(json.dumps(volantino, ensure_ascii=False), "utf-8")
        risultato.append(volantino)
    return risultato


# --- I prodotti, volantino per volantino

def prodotti_bennet(volantino, oggi):
    """Bennet: le pagine e la posizione di ogni prodotto dal visualizzatore; i nomi da DoveConviene, che ne dà circa 100 a volantino.

    Il prezzo vero è nella foto: il numero che danno a parte a volte è sbagliato, e non lo uso.
    Gli altri nomi si leggono dalla pagina con l'OCR. I prodotti senza foto propria si ritagliano dalla pagina nel browser.
    """
    pagina = testo(BASE_BENNET + volantino["chiave"])
    nomi = {}
    for dato in blocchi_json_ld(pagina):
        if dato.get("@type") == "Product" and dato.get("image"):
            codice = re.search(r"gibCover_([0-9a-f-]{36})_", dato["image"][0])
            if codice:
                nomi[codice.group(1)] = (html.unescape(dato.get("name", "")).strip(), dato["image"][0])
    pubblicazione = re.search(r'"publicationId":"it_it_(\d+)"', pagina)
    if not pubblicazione:
        raise NonLetto("Bennet: non trovo il numero del volantino")
    base = f"https://shopfully-publication-api.global.ssl.fastly.net/publication_pages/it_it/{pubblicazione.group(1)}"
    pagine, elenco = {}, []
    for parte in range(1, 21):
        try:
            blocco = json.loads(testo(f"{base}/{parte}"))
        except NonLetto:
            break  # le parti finiscono con un errore 404
        numeri = sorted((k for k in blocco if k.isdigit()), key=int)
        if not numeri:
            break
        posti = {}
        for numero in numeri:
            vista = max(blocco[numero]["pageRepresentationDescriptors"], key=lambda v: v.get("width", 0))
            pagine[numero] = "https://" + vista["pageRepresentation"]["resourcePath"]
            volantino.setdefault("proporzione", round(vista["height"] / vista["width"], 4))
            for arricchimento in blocco[numero].get("pageEnrichments", []):
                posti[arricchimento["bundlePath"]] = True
        for indirizzo in posti:
            for numero, voci in json.loads(testo("https://" + indirizzo)).items():
                if not numero.isdigit():
                    continue
                for voce in voci:
                    forma = voce.get("crop_shape")
                    if not forma:
                        continue
                    nome, foto = nomi.get(voce["id"], ("", ""))
                    elemento = {
                        "id": voce["id"],
                        "nome": nome,
                        "foto": foto,
                        "pag": int(numero),
                        "riquadro": [round(forma["x"], 4), round(forma["y"], 4),
                                     round(forma["x"] + forma["width"], 4), round(forma["y"] + forma["height"], 4)],
                    }
                    elenco.append(elemento)
    volantino["pagine"] = pagine
    nomi_da_ocr(volantino, elenco)
    for elemento in elenco:
        elemento.pop("id", None)
        elemento["cat"] = categorie.categoria(elemento["nome"]) if elemento["nome"] else categorie.SENZA_NOME
    elenco.sort(key=lambda e: e["pag"])
    return elenco


PAROLE_NON_NOME = {"SPACCA", "PREZZI", "PEZZI", "DISPONIBILI", "ACQUISTABILI", "ACQUISTABILE", "MAXI", "FORMATO", "SCONTO", "OFFERTA",
                   "BENNET", "NOVITA", "NUOVO", "SOTTOCOSTO", "CONVIENE", "PREZZO", "BASSO", "GRATIS", "SUI", "PRODOTTI"}


def parole_della_pagina(immagine):
    """Le parole lette dall'OCR, con la loro posizione in frazioni di pagina."""
    uscita = subprocess.run(["tesseract", str(immagine), "stdout", "--psm", "11", "-l", "eng", "tsv"],
                            capture_output=True, timeout=180, check=True).stdout.decode("utf-8", "replace")
    righe = list(csv.DictReader(io.StringIO(uscita), delimiter="\t", quoting=csv.QUOTE_NONE))
    pagina = next(r for r in righe if r["level"] == "1")
    largo, alto = int(pagina["width"]), int(pagina["height"])
    parole = []
    for r in righe:
        scritto = (r.get("text") or "").strip()
        if r["level"] != "5" or len(scritto) < 3 or float(r["conf"]) < 55:
            continue
        ordine = (int(r["block_num"]), int(r["par_num"]), int(r["line_num"]), int(r["word_num"]))
        parole.append((ordine, scritto, (int(r["left"]) + int(r["width"]) / 2) / largo, (int(r["top"]) + int(r["height"]) / 2) / alto))
    return sorted(parole)


def nome_nel_riquadro(parole, riquadro):
    """Il nome nei volantini Bennet è scritto in maiuscolo: si tengono le parole maiuscole dentro il riquadro."""
    x0, y0, x1, y1 = riquadro
    scelte = []
    for _, scritto, cx, cy in parole:
        if x0 <= cx <= x1 and y0 <= cy <= y1 and re.fullmatch(r"[A-ZÀ-Ù][A-ZÀ-Ù'’.-]{2,}", scritto) and scritto not in PAROLE_NON_NOME:
            scelte.append(scritto)
    return ritagli.bella_scrittura(" ".join(scelte))[:80]


def nomi_da_ocr(volantino, elenco):
    """I prodotti senza nome: lo legge dalla pagina, una volta sola per volantino. Senza tesseract restano senza nome."""
    if not shutil.which("tesseract"):
        return
    memoria = USCITA / "img" / volantino["chiave"] / "ocr.json"
    letti = json.loads(memoria.read_text("utf-8")) if memoria.exists() else {}
    da_leggere = sorted({e["pag"] for e in elenco if not e["nome"] and e["id"] not in letti})
    for numero in da_leggere:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as immagine:
            immagine.write(scarica(volantino["pagine"][str(numero)]))
            immagine.flush()
            parole = parole_della_pagina(immagine.name)
        for elemento in elenco:
            if elemento["pag"] == numero and not elemento["nome"]:
                letti[elemento["id"]] = nome_nel_riquadro(parole, elemento["riquadro"])
    if da_leggere:
        memoria.parent.mkdir(parents=True, exist_ok=True)
        memoria.write_text(json.dumps(letti, ensure_ascii=False), "utf-8")
    for elemento in elenco:
        if not elemento["nome"] and letti.get(elemento["id"]):
            elemento["nome"] = letti[elemento["id"]]
            elemento["letto"] = True


def posizioni_carrefour(volantino):
    """Le pagine del volantino e i riquadri dei prodotti: il codice del riquadro è nel nome del file della foto."""
    pagina = html.unescape(testo(volantino["url"]))
    trovato = re.search(r"[^\"'\s]*Volantini-Pages\?[^\"'\s]+", pagina)
    if not trovato:
        return {}, {}, pagina
    indirizzo = trovato.group(0) if trovato.group(0).startswith("http") else "https://www.carrefour.it" + trovato.group(0)
    corpo = testo(indirizzo)
    pagine, riquadri = {}, {}
    for numero, fetta in enumerate(corpo.split("swiper-zoom-target")[1:], start=1):
        grande = re.search(r"zoom='([^']+)'", fetta) or re.search(r'data-src="([^"]+)"', fetta)
        if grande:
            pagine[str(numero)] = grande.group(1)
        for codice, l, a, sopra, sinistra in re.findall(
                r'<div id="a-(\d+)" class="layer_item" style="width: ([\d.]+)%; height: ([\d.]+)%; top: ([\d.]+)%; left: ([\d.]+)%;', fetta):
            l, a, sopra, sinistra = (float(v) / 100 for v in (l, a, sopra, sinistra))
            riquadri.setdefault(codice, (numero, [round(sinistra, 4), round(sopra, 4), round(sinistra + l, 4), round(sopra + a, 4)]))
    return pagine, riquadri, pagina


def etichette_carrefour(volantino, pagina):
    """Quale categoria ufficiale ha ogni prodotto: il menu del volantino, una voce alla volta."""
    etichette = {}
    for voce in sorted(set(re.findall(r"\?label=([^\"&]+)\"", pagina))):
        nome_etichetta = urllib.parse.unquote(voce).lower()
        if nome_etichetta not in categorie.CARREFOUR:
            continue
        menu = html.unescape(testo(volantino["url"] + "?label=" + urllib.parse.quote(nome_etichetta)))
        trovato = re.search(r"/on/demandware\.store/[^\"'\s]*Volantini-Search\?[^\"'\s]+", menu)
        if not trovato:
            continue
        for inizio in range(0, 2000, 25):
            pezzo = testo(f"https://www.carrefour.it{trovato.group(0)}&start={inizio}&sz=25")
            codici = re.findall(r'data-pid="([^"]+)"', pezzo)
            nuovi = [c for c in codici if c not in etichette]
            for codice in nuovi:
                etichette[codice] = nome_etichetta
            if not nuovi or len(codici) < 25:
                break
            time.sleep(0.15)
    return etichette


def prodotti_carrefour(volantino, oggi):
    """L'elenco ufficiale, con foto, prezzo, categoria e posto sulla pagina. Si legge una volta sola per volantino."""
    cartella = USCITA / "img" / volantino["chiave"]
    salvati = cartella / "prodotti.json"
    if salvati.exists():
        memoria = json.loads(salvati.read_text("utf-8"))
        volantino["pagine"] = memoria["pagine"]
        for elemento in memoria["prodotti"]:
            elemento["cat"] = categorie.categoria_carrefour(elemento["nome"], elemento.get("etichetta"))
        return memoria["prodotti"]
    pagine, riquadri, pagina = posizioni_carrefour(volantino)
    trovato = re.search(r"/on/demandware\.store/[^\"'\s]*Volantini-Search\?[^\"'\s]+", pagina)
    if not trovato:
        raise NonLetto(f"Carrefour {volantino['titolo']}: elenco non trovato")
    etichette = etichette_carrefour(volantino, pagina)
    base = "https://www.carrefour.it" + trovato.group(0)
    elenco, visti = [], set()
    for inizio in range(0, 5000, 25):
        pezzo = testo(f"{base}&start={inizio}&sz=25")
        schede = re.findall(r'<div class="product tile.*?(?=<div class="product-item|\Z)', pezzo, re.S)
        nuovi = 0
        for scheda in schede:
            codice = re.search(r'data-pid="([^"]+)"', scheda)
            nome = re.search(r'class="tile-description"[^>]*title="([^"]*)"', scheda)
            prezzo = re.search(r'd-prices__final[^>]*>\s*<strong>([^<]+)', scheda)
            foto = re.search(r'data-src="([^"]+)"', scheda)
            unita = re.search(r'd-prices__partial[^>]*>([^<]+)', scheda)
            if not codice or codice.group(1) in visti or not nome:
                continue
            visti.add(codice.group(1))
            nuovi += 1
            indirizzo_foto = foto.group(1) if foto else ""
            nome_pulito = html.unescape(nome.group(1)).strip()
            elemento = {
                "nome": nome_pulito,
                "prezzi": [html.unescape(prezzo.group(1)).replace("€", "").strip()] if prezzo else [],
                "unita": re.sub(r"\s+", " ", html.unescape(unita.group(1))).strip() if unita else "",
                "foto": ("https://www.carrefour.it" if indirizzo_foto.startswith("/") else "") + indirizzo_foto,
                "etichetta": etichette.get(codice.group(1)),
                "cat": categorie.categoria_carrefour(nome_pulito, etichette.get(codice.group(1))),
            }
            numero_foto = re.search(r"/(\d{6,})(?:_\d+)?\.(?:jpg|jpeg|png)", indirizzo_foto)
            posto = riquadri.get(str(int(numero_foto.group(1)))) if numero_foto else None
            if posto:
                elemento["pag"], elemento["riquadro"] = posto
            elenco.append(elemento)
        if not nuovi:
            break
        time.sleep(0.15)
    if elenco:
        cartella.mkdir(parents=True, exist_ok=True)
        salvati.write_text(json.dumps({"prodotti": elenco, "pagine": pagine}, ensure_ascii=False), "utf-8")
    volantino["pagine"] = pagine
    return elenco


def prodotti_pdf(volantino, oggi, usa_date_di_pagina):
    """I ritagli dal PDF. Si fanno una volta sola per volantino: restano in docs/img/<chiave>."""
    cartella = USCITA / "img" / volantino["chiave"]
    salvati = cartella / "prodotti.json"
    if salvati.exists():
        memoria = json.loads(salvati.read_text("utf-8"))
        elenco, pagine = memoria["prodotti"], memoria["pagine"]
    else:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as file_pdf:
            file_pdf.write(scarica(volantino["pdf"], timeout=180))
            file_pdf.flush()
            elenco, pagine = ritagli.ritaglia_volantino(file_pdf.name, cartella, f"img/{volantino['chiave']}")
        salvati.write_text(json.dumps({"prodotti": elenco, "pagine": pagine}, ensure_ascii=False), "utf-8")
    volantino["pagine"] = pagine
    uscita = []
    for voce in elenco:
        nuova = {k: voce[k] for k in ("nome", "prezzi", "pag", "foto", "riquadro")}
        nuova["cat"] = categorie.SENZA_NOME if voce["nome"].startswith("Offerta a pag") else categorie.categoria(voce["nome"])
        # Coop scrive su ogni pagina da quando a quando vale. Su Conad le stesse parole sono banner di una sola offerta.
        if voce.get("finestra") and usa_date_di_pagina:
            mi, gi, mf, gf = voce["finestra"]
            dal, al = data_vicina(gi, mi, oggi).isoformat(), data_vicina(gf, mf, oggi).isoformat()
            if (dal, al) != (volantino["dal"], volantino["al"]):
                nuova["dal"], nuova["al"] = dal, al
        if voce.get("fino_a") and volantino.get("al_extra"):
            fine = data_vicina(voce["fino_a"][1], voce["fino_a"][0], oggi).isoformat()
            if fine == volantino["al_extra"]:
                nuova["al"] = fine
        uscita.append(nuova)
    return uscita


def aggiungi_prodotti(negozio, volantini, precedenti, oggi):
    """Solo i volantini principali. Se uno non si legge, tiene l'elenco dell'ultima volta e lo segnala."""
    vecchi = {v["chiave"]: v for v in precedenti.get("volantini", [])}
    errori = []
    for volantino in volantini:
        if volantino["tipo"] != "principale":
            continue
        try:
            if negozio["lettore"] == "carrefour":
                volantino["prodotti"] = prodotti_carrefour(volantino, oggi)
            elif negozio["id"] == "bennet":
                volantino["prodotti"] = prodotti_bennet(volantino, oggi)
            elif volantino.get("pdf"):
                volantino["prodotti"] = prodotti_pdf(volantino, oggi, negozio["id"] == "coop")
            if not volantino.get("prodotti"):
                raise NonLetto("nessun prodotto trovato")
        except Exception as errore:  # un volantino rotto non deve fermare gli altri
            errori.append(f"{negozio['nome']}, {volantino['titolo']}: {errore}")
            vecchio = vecchi.get(volantino["chiave"], {})
            volantino["prodotti"] = vecchio.get("prodotti", [])
            volantino["pagine"] = vecchio.get("pagine", {})
            volantino["prodotti_vecchi"] = True
    return errori


LETTORI = {"bennet": leggi_bennet, "conad": leggi_conad, "carrefour": leggi_carrefour, "coop": leggi_coop}


def completa(volantini, oggi):
    """Toglie gli scaduti, aggiunge tipo e note a mano, mette in ordine."""
    tenuti = []
    for volantino in volantini:
        if max(volantino["al"], volantino.get("al_extra", "")) < oggi.isoformat():
            continue
        volantino["tipo"] = tipo_di(volantino["titolo"])
        if volantino["chiave"] in NOTE_A_MANO:
            volantino["note"] = NOTE_A_MANO[volantino["chiave"]]
        tenuti.append(volantino)
    return sorted(tenuti, key=lambda v: (v["tipo"] != "principale", v["dal"], v["al"]))


def main():
    adesso = dt.datetime.now(ROMA)
    oggi = adesso.date()
    USCITA.mkdir(exist_ok=True)
    percorso_dati = USCITA / "dati.json"
    precedenti = {}
    if percorso_dati.exists():
        precedenti = {n["id"]: n for n in json.loads(percorso_dati.read_text("utf-8"))["negozi"]}

    negozi, errori = [], []
    for negozio in NEGOZI:
        scheda = {k: negozio[k] for k in ("id", "nome", "dove", "fonte")}
        try:
            letti = LETTORI[negozio["lettore"]](negozio, oggi)
            if not letti:
                raise NonLetto("nessun volantino trovato: forse la pagina è cambiata")
            scheda["volantini"] = completa(letti, oggi)
            scheda["letto"] = adesso.isoformat(timespec="minutes")
            errori += aggiungi_prodotti(negozio, scheda["volantini"], precedenti.get(negozio["id"], {}), oggi)
        except Exception as errore:  # un negozio rotto non deve fermare gli altri
            errori.append(f"{negozio['nome']}: {errore}")
            vecchia = precedenti.get(negozio["id"], {})
            scheda["volantini"] = vecchia.get("volantini", [])
            scheda["letto"] = vecchia.get("letto")
            scheda["errore"] = True
        negozi.append(scheda)

    # I ritagli dei volantini che non ci sono più si buttano
    cartella_img = USCITA / "img"
    if cartella_img.exists():
        vivi = {v["chiave"] for n in negozi for v in n["volantini"]}
        for sotto in cartella_img.iterdir():
            if sotto.is_dir() and sotto.name not in vivi:
                shutil.rmtree(sotto)

    dati = {"aggiornato": adesso.isoformat(timespec="minutes"), "negozi": negozi,
            "categorie": categorie.ORDINE + [categorie.SENZA_NOME]}
    percorso_dati.write_text(json.dumps(dati, ensure_ascii=False, indent=1) + "\n", "utf-8")
    incorporati = json.dumps(dati, ensure_ascii=False).replace("<", "\\u003c")
    pagina = MODELLO.read_text("utf-8").replace("/*DATI*/null", incorporati)
    (USCITA / "index.html").write_text(pagina, "utf-8")

    for riga in errori:
        print("ERRORE", riga, file=sys.stderr)
    for negozio in negozi:
        print(negozio["nome"], sum(len(v.get("prodotti", [])) for v in negozio["volantini"]), "prodotti")
    print(f"{sum(len(n['volantini']) for n in negozi)} volantini, {len(errori)} errori")
    return 3 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
