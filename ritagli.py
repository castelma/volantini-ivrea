#!/usr/bin/env python3
"""Taglia un volantino PDF in un'immagine per prodotto, col suo nome e prezzo.

Non c'è un elenco dei prodotti da nessuna parte: si parte dai prezzi grandi scritti nel PDF
e si divide la pagina finché ogni pezzo ha un prezzo solo, tagliando dove non si taglia niente
(testi e foto si sanno dove stanno, da pdftohtml). Il ritaglio mostra il volantino vero,
quindi il prezzo che conta è quello che si vede nella foto.
Serve poppler: pdftohtml e pdftoppm. Prova: python3 ritagli.py volantino.pdf cartella_uscita
"""
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DPI = 130
LARGHEZZA_PAGINA = 1240  # pixel delle immagini di pagina: bastano per leggere ingrandendo
PREZZO_SOLO = re.compile(r"^\s*€?\s*(\d{1,3}),(\d{2})\s*€?\s*$")
INTERO = re.compile(r"^\s*€?\s*(\d{1,3})\s*$")
DECIMALI = re.compile(r"^\s*,\s*(\d{2})\s*€?\s*$")
# Quello che in un riquadro non è il nome del prodotto
NON_NOME = re.compile(
    r"€|%|\bal (kg|l|lt|pz)\b|^\s*(sotto|costo|sotto ?costo|conviene|sconto|sconto (soci|clienti)|soci|clienti|"
    r"solo per i( soci)?|solo per|per i soci|reparto surgelati|reparto freschi|solo titolari|vale|bollino|offerta|"
    r"offerta da non perdere|da non|perdere|doppio|doppio sconto|n° pezzi.*|pezzi.*|fino a.*|prezzi validi.*|"
    r"\d+\s*\+\s*\d+|\d+|gratis|pezzi gratis|ai soci.*|bassi e fissi|nuovo|novità|maxi formato)\s*$",
    re.I,
)


def leggi_pagine(percorso_pdf):
    """Testi con grandezza e posizione, e posizione delle immagini, pagina per pagina."""
    with tempfile.TemporaryDirectory() as temporanea:
        subprocess.run(["pdftohtml", "-xml", "-zoom", "1", "-nodrm", "-q", str(percorso_pdf), f"{temporanea}/p"],
                       capture_output=True, timeout=600, check=True)
        xml = Path(f"{temporanea}/p.xml").read_text("utf-8", "replace")
    grandezze = {m.group(1): int(m.group(2)) for m in re.finditer(r'<fontspec id="(\d+)" size="(\d+)"', xml)}
    pagine = []
    for blocco in re.finditer(r'<page number="(\d+)"[^>]*height="(\d+)" width="(\d+)">(.*?)</page>', xml, re.S):
        numero, alto, largo, corpo = int(blocco.group(1)), int(blocco.group(2)), int(blocco.group(3)), blocco.group(4)
        testi = []
        for t in re.finditer(r'<text top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)" font="(\d+)">(.*?)</text>', corpo, re.S):
            sopra, sinistra, l, a = map(int, t.groups()[:4])
            scritto = html.unescape(re.sub(r"<[^>]+>", "", t.group(6))).strip()
            if scritto:
                testi.append({"x0": sinistra, "y0": sopra, "x1": sinistra + l, "y1": sopra + a,
                              "size": grandezze.get(t.group(5), 0), "t": scritto, "tipo": "testo"})
        immagini = []
        for i in re.finditer(r'<image top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)"', corpo):
            sopra, sinistra, l, a = map(int, i.groups())
            if l >= 3 and a >= 3:
                immagini.append({"x0": sinistra, "y0": sopra, "x1": sinistra + l, "y1": sopra + a, "tipo": "foto"})
        pagine.append({"n": numero, "w": largo, "h": alto, "testi": testi, "immagini": immagini})
    return pagine


def trova_prezzi(testi):
    """I prezzi grandi di una pagina: 8 + ,60 in due pezzi, oppure 5,99 in uno."""
    if not testi:
        return []
    grandezze = sorted(t["size"] for t in testi)
    mediana = grandezze[len(grandezze) // 2]
    soglia = max(16, mediana * 1.5)
    ancore, usati = [], set()
    for indice, t in enumerate(testi):
        if t["size"] < soglia:
            continue
        intero = INTERO.match(t["t"])
        if intero:
            for j, d in enumerate(testi):
                decimali = DECIMALI.match(d["t"])
                if decimali and j not in usati and -3 <= d["x0"] - t["x1"] <= t["size"] * 0.8 and d["y0"] < t["y1"] and d["y1"] > t["y0"]:
                    usati.add(j)
                    ancore.append({"x0": t["x0"], "y0": t["y0"], "x1": d["x1"], "y1": max(t["y1"], d["y1"]),
                                   "prezzi": [f"{intero.group(1)},{decimali.group(1)}"]})
                    break
            continue
        solo = PREZZO_SOLO.match(t["t"])
        if solo:
            ancore.append({"x0": t["x0"], "y0": t["y0"], "x1": t["x1"], "y1": t["y1"],
                           "prezzi": [f"{solo.group(1)},{solo.group(2)}"]})
    for a in ancore:
        for t in testi:
            if t["t"] == "€" and -2 <= t["x0"] - a["x1"] <= 8 and t["y0"] < a["y1"] and t["y1"] > a["y0"]:
                a["x1"] = max(a["x1"], t["x1"])
    return unisci_vicini(ancore)


def unisci_vicini(ancore):
    """Due prezzi affiancati nello stesso riquadro (clienti e soci) restano un prodotto solo."""
    ancore = sorted(ancore, key=lambda a: (a["y0"], a["x0"]))
    tenuti = []
    for a in ancore:
        for b in tenuti:
            stessa_riga = a["y0"] < b["y1"] and a["y1"] > b["y0"]
            if stessa_riga and -2 <= a["x0"] - b["x1"] <= 12:
                b["x1"] = max(b["x1"], a["x1"])
                b["y1"] = max(b["y1"], a["y1"])
                b["prezzi"] += a["prezzi"]
                break
        else:
            tenuti.append(dict(a))
    return tenuti


def centro(o, asse):
    return (o["x0"] + o["x1"]) / 2 if asse == "x" else (o["y0"] + o["y1"]) / 2


def sopra_stessa_colonna(t, a, tolleranza=15):
    return t["y1"] <= a["y0"] + 2 and t["x0"] < a["x1"] + tolleranza and t["x1"] > a["x0"] - tolleranza


def e_titolo(t):
    lettere = [c for c in t["t"] if c.isalpha()]
    if len(lettere) < 3 or NON_NOME.search(t["t"]):
        return False
    return sum(c.isupper() for c in lettere) / len(lettere) > 0.7 and t["y1"] - t["y0"] <= (t["x1"] - t["x0"]) * 3


def abbina_nomi(ancore, testi, largo, alto):
    """Allarga ogni prezzo fino al suo nome, sopra o di fianco, e alla riga del prezzo al chilo, sotto.

    Da qui in poi nome e prezzo sono un pezzo solo: i tagli non li possono separare.
    Se un prezzo non ha un nome tutto suo e ne ha un altro appena sopra, è lo stesso prodotto in un altro formato.
    """
    occupati = set()

    def distanza(t, a):
        dx = max(a["x0"] - t["x1"], t["x0"] - a["x1"], 0)
        dy = max(a["y0"] - t["y1"], t["y0"] - a["y1"], 0)
        sopra = t["y1"] <= a["y0"] + 2 and dx <= 15 and dy <= alto * 0.22
        accanto = dy <= 12 and dx <= largo * 0.2
        return dx + dy if sopra or accanto else None

    def libero(t, a):
        x0, x1 = min(t["x0"], a["x0"]), max(t["x1"], a["x1"])
        y0, y1 = min(t["y0"], a["y0"]), max(t["y1"], a["y1"])
        return not any(b is not a and x0 < centro(b, "x") < x1 and y0 < centro(b, "y") < y1 for b in ancore)

    for a in sorted(ancore, key=lambda a: -a["y0"]):
        candidati = []
        for t in testi:
            if id(t) in occupati or not e_titolo(t) or t["y0"] > a["y1"]:
                continue
            d = distanza(t, a)
            if d is not None and libero(t, a):
                candidati.append((d, t["y0"], t["x0"], len(candidati), t))
        a["titolo"] = None
        if candidati:
            primo = min(candidati)[-1]
            gruppo = [primo]
            while True:
                sopra = gruppo[-1]
                altezza = sopra["y1"] - sopra["y0"]
                vicini = [t for t in testi if id(t) not in occupati and t not in gruppo and e_titolo(t)
                          and t["y0"] < sopra["y0"] - 2 and t["y1"] <= sopra["y0"] + altezza * 0.45
                          and sopra["y0"] - t["y1"] <= altezza * 0.8
                          and t["x0"] < sopra["x1"] + 8 and t["x1"] > sopra["x0"] - 8]
                if not vicini:
                    break
                gruppo.append(max(vicini, key=lambda t: t["y1"]))
            occupati.update(id(t) for t in gruppo)
            a["titolo"] = min(t["y0"] for t in gruppo)
            a["x0"] = min(a["x0"], min(t["x0"] for t in gruppo))
            a["x1"] = max(a["x1"], max(t["x1"] for t in gruppo))
            a["y0"] = min(a["y0"], a["titolo"])
    # Formati diversi dello stesso prodotto: un prezzo senza nome sotto a uno che ce l'ha
    tenute = []
    for a in sorted(ancore, key=lambda a: a["y0"]):
        padre = None
        if a["titolo"] is None:
            for b in tenute:
                if b["y1"] <= a["y0"] + 2 and a["y0"] - b["y1"] < 60 and b["x0"] < a["x1"] and b["x1"] > a["x0"]:
                    padre = b
        if padre is not None:
            padre["prezzi"] += a["prezzi"]
            padre["x0"], padre["x1"] = min(padre["x0"], a["x0"]), max(padre["x1"], a["x1"])
            padre["y1"] = max(padre["y1"], a["y1"])
        else:
            tenute.append(a)
    # La riga piccola sotto il prezzo (prezzo al chilo) resta col prezzo
    for a in tenute:
        for t in sorted(testi, key=lambda t: t["y0"]):
            if t["y0"] >= a["y1"] - 3 and t["y0"] - a["y1"] <= 14 and t["size"] <= 12 \
                    and t["x0"] < a["x1"] and t["x1"] > a["x0"] and not e_titolo(t):
                a["y1"] = max(a["y1"], t["y1"])
    return tenute


def taglia(regione, ancore, oggetti, area_pagina):
    """Divide la regione finché ogni pezzo ha un prezzo solo. Regione = (x0, y0, x1, y1)."""
    if len(ancore) <= 1:
        return [(regione, ancore[0])] if ancore else []
    interni = [o for o in oggetti if o["x1"] > regione[0] and o["x0"] < regione[2]
               and o["y1"] > regione[1] and o["y0"] < regione[3]]
    migliore = None
    for asse, (basso, alto) in (("x", (regione[0], regione[2])), ("y", (regione[1], regione[3]))):
        a0, a1 = f"{asse}0", f"{asse}1"
        ordinate = sorted(ancore, key=lambda a: centro(a, asse))
        primo, ultimo = centro(ordinate[0], asse), centro(ordinate[-1], asse)
        bordi = sorted({primo, ultimo} | {o[k] for o in interni for k in (a0, a1) if primo < o[k] < ultimo})
        for s, d in zip(bordi, bordi[1:]):
            c = (s + d) / 2
            if not any(centro(a, asse) < c for a in ancore) or not any(centro(a, asse) > c for a in ancore):
                continue
            costo = 0.0
            for o in interni:
                margine = 2 if o["tipo"] == "foto" else 0
                if o[a0] + margine < c < o[a1] - margine:
                    if o["tipo"] == "testo":
                        costo += 1000
                    else:
                        quota = (o["x1"] - o["x0"]) * (o["y1"] - o["y0"]) / area_pagina
                        costo += 0 if quota > 0.3 else 1 + quota * 500
            if any(a[a0] < c < a[a1] for a in ancore):
                costo += 100000
            voto = (costo, -(d - s))
            if migliore is None or voto < migliore[0]:
                migliore = (voto, asse, c)
    if migliore is None:  # due prezzi uno sopra l'altro: non c'è altro modo di separarli
        ordinate = sorted(ancore, key=lambda a: centro(a, "y"))
        asse, c = "y", (centro(ordinate[0], "y") + centro(ordinate[1], "y")) / 2
    else:
        _, asse, c = migliore
    if asse == "x":
        prima, dopo = (regione[0], regione[1], c, regione[3]), (c, regione[1], regione[2], regione[3])
    else:
        prima, dopo = (regione[0], regione[1], regione[2], c), (regione[0], c, regione[2], regione[3])
    return (taglia(prima, [a for a in ancore if centro(a, asse) < c], oggetti, area_pagina)
            + taglia(dopo, [a for a in ancore if centro(a, asse) >= c], oggetti, area_pagina))


def scatola(regione, ancora, oggetti, ancore, largo, alto):
    """Il riquadro da ritagliare: lo sfondo del prodotto se c'è, se no nome, prezzo e foto del pezzo."""
    area_pagina = largo * alto
    celle = []
    for o in oggetti:
        if o["tipo"] != "foto":
            continue
        quota = (o["x1"] - o["x0"]) * (o["y1"] - o["y0"]) / area_pagina
        if 0.03 <= quota <= 0.3 and o["x0"] - 3 <= ancora["x0"] and o["x1"] + 3 >= ancora["x1"] \
                and o["y0"] - 3 <= ancora["y0"] and o["y1"] + 3 >= ancora["y1"] \
                and not any(b is not ancora and o["x0"] < centro(b, "x") < o["x1"] and o["y0"] < centro(b, "y") < o["y1"]
                            for b in ancore):
            celle.append((quota, o))
    if celle:
        cella = min(celle, key=lambda c: c[0])[1]
        return (max(0, cella["x0"]), max(0, cella["y0"]), min(largo, cella["x1"]), min(alto, cella["y1"]))
    x0, y0, x1, y1 = ancora["x0"], ancora["y0"], ancora["x1"], ancora["y1"]
    for o in oggetti:
        if o["tipo"] != "foto" or (o["x1"] - o["x0"]) * (o["y1"] - o["y0"]) / area_pagina > 0.3:
            continue
        cx, cy = centro(o, "x"), centro(o, "y")
        if not (regione[0] <= cx <= regione[2] and regione[1] <= cy <= regione[3]):
            continue
        if o["y1"] < alto * 0.09 or o["y0"] > alto * 0.95:  # testata e piede della pagina
            continue
        x0, y0, x1, y1 = min(x0, o["x0"]), min(y0, o["y0"]), max(x1, o["x1"]), max(y1, o["y1"])
    x0, y0 = max(x0, regione[0] - 3), max(y0, regione[1] - 5)
    x1, y1 = min(x1, regione[2] + 3), min(y1, regione[3] + 5)
    return (max(0, x0 - 4), max(0, y0 - 5), min(largo, x1 + 4), min(alto, y1 + 5))


def nome_da(ancora, testi):
    """Il nome: le righe sopra il prezzo dentro il pezzo, senza prezzi, sconti e scritte fisse."""
    righe = []
    for t in sorted(testi, key=lambda t: (t["y0"], t["x0"])):
        if not (ancora["x0"] - 4 <= centro(t, "x") <= ancora["x1"] + 4 and ancora["y0"] - 2 <= centro(t, "y") <= ancora["y1"]):
            continue
        if t["y1"] - t["y0"] > (t["x1"] - t["x0"]) * 3:  # testo in verticale: note legali
            continue
        if NON_NOME.search(t["t"]) or DECIMALI.match(t["t"]) or INTERO.match(t["t"]) or len(t["t"]) < 2:
            continue
        righe.append(re.sub(r"\s+", " ", t["t"]))
    nome = " ".join(righe[:6]).strip()
    return re.sub(r"(ff)\s(?=[a-zà-ù])", r"\1", nome)[:110]


def bella_scrittura(nome):
    """DA TUTTO MAIUSCOLO a una forma leggibile, lasciando stare il resto."""
    piccole = {"DI", "DE", "DEL", "DA", "IN", "CON", "AL", "ALLA", "E", "O", "LA", "LE", "IL", "PER", "SU", "A"}
    parole = []
    for parola in nome.split(" "):
        if parola.upper() in piccole and parola.isupper():
            parole.append(parola.lower())
        elif parola.isupper() and len(parola) > 3:
            parole.append(parola.capitalize())
        else:
            parole.append(parola)
    return " ".join(parole)


MESI = {m: i + 1 for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}
FINESTRA = re.compile(r"\bdal\s+(\d{1,2})(?:\s+([a-zà-ù]+))?\s+all?['’\s]\s*(\d{1,2})\s+([a-zà-ù]+)", re.I)
ALTRE_OFFERTE = re.compile(r"ETANTEALTREOFFERTEFINOA(?:[A-ZÌ]+?)?(\d{1,2})([A-Z]+)")


def blocchi_pdf(percorso_pdf):
    """Per ogni pagina i blocchi di testo con la loro altezza. Serve pdftotext: pdftohtml perde le scritte in verticale."""
    uscita = subprocess.run(["pdftotext", "-bbox-layout", str(percorso_pdf), "-"],
                            capture_output=True, timeout=300, check=True).stdout.decode("utf-8", "replace")
    pagine = {}
    for numero, pagina in enumerate(re.findall(r"<page .*?</page>", uscita, re.S), start=1):
        blocchi = []
        for y0, y1, corpo in re.findall(r'<block xMin="[\d.]+" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">(.*?)</block>', pagina, re.S):
            parole = re.findall(r"<word[^>]*>([^<]*)</word>", corpo)
            blocchi.append((html.unescape(" ".join(parole)), (float(y0) + float(y1)) / 2))
        pagine[numero] = blocchi
    return pagine


def finestre_pagina(blocchi):
    """Le date scritte nella pagina («dal 5 all'11 novembre»), ciascuna con la sua altezza."""
    finestre = []
    for scritto, altezza in blocchi:
        for gi, mi, gf, mf in FINESTRA.findall(scritto):
            mese_fine = MESI.get(mf.lower())
            mese_inizio = MESI.get(mi.lower()) if mi else mese_fine
            if mese_fine and mese_inizio:
                finestre.append(([mese_inizio, int(gi), mese_fine, int(gf)], altezza))
    return finestre


def fino_a_pagina(blocchi):
    """Sottocosto Conad: sulle pagine «e tante altre offerte fino a mercoledì 18 novembre» vale quella data."""
    tutto = re.sub(r"\s+", "", " ".join(b[0] for b in blocchi)).upper()
    trovato = ALTRE_OFFERTE.search(tutto)
    if trovato and MESI.get(trovato.group(2).lower()):
        return [MESI[trovato.group(2).lower()], int(trovato.group(1))]
    return None


def ritaglia_volantino(percorso_pdf, cartella_uscita, prefisso_url):
    """Scrive le immagini in cartella_uscita e restituisce i prodotti e le pagine."""
    uscita = Path(cartella_uscita)
    uscita.mkdir(parents=True, exist_ok=True)
    prodotti, pagine = [], {}
    date_scritte = blocchi_pdf(percorso_pdf)
    for pagina in leggi_pagine(percorso_pdf):
        ancore = abbina_nomi(trova_prezzi(pagina["testi"]), pagina["testi"], pagina["w"], pagina["h"])
        if not ancore:
            continue
        oggetti = pagina["testi"] + pagina["immagini"]
        area = pagina["w"] * pagina["h"]
        pezzi = taglia((0, 0, pagina["w"], pagina["h"]), ancore, oggetti, area)
        finestre = finestre_pagina(date_scritte.get(pagina["n"], []))
        fino_a = fino_a_pagina(date_scritte.get(pagina["n"], []))
        for indice, (regione, ancora) in enumerate(pezzi, start=1):
            x0, y0, x1, y1 = scatola(regione, ancora, oggetti, ancore, pagina["w"], pagina["h"])
            scala = DPI / 72
            nome_file = f"p{pagina['n']:02d}_{indice:02d}"
            base = str(uscita / nome_file)
            subprocess.run(
                ["pdftoppm", "-f", str(pagina["n"]), "-l", str(pagina["n"]), "-r", str(DPI),
                 "-x", str(int(x0 * scala)), "-y", str(int(y0 * scala)),
                 "-W", str(int((x1 - x0) * scala)), "-H", str(int((y1 - y0) * scala)),
                 "-jpeg", "-jpegopt", "quality=72,optimize=y", "-singlefile", str(percorso_pdf), base],
                capture_output=True, timeout=120, check=True)
            voce = {
                "nome": bella_scrittura(nome_da(ancora, pagina["testi"])) or f"Offerta a pag. {pagina['n']}",
                "prezzi": ancora["prezzi"],
                "pag": pagina["n"],
                "foto": f"{prefisso_url}/{nome_file}.jpg",
                "riquadro": [round(x0 / pagina["w"], 4), round(y0 / pagina["h"], 4),
                             round(x1 / pagina["w"], 4), round(y1 / pagina["h"], 4)],
            }
            if finestre:  # più date sulla stessa pagina: vale quella alla stessa altezza
                voce["finestra"] = min(finestre, key=lambda f: abs(f[1] - centro(ancora, "y")))[0]
            if fino_a:
                voce["fino_a"] = fino_a
            prodotti.append(voce)
        # La pagina intera, per vedere il ritaglio al suo posto
        nome_pagina = f"pagina_{pagina['n']:02d}"
        subprocess.run(
            ["pdftoppm", "-f", str(pagina["n"]), "-l", str(pagina["n"]),
             "-r", str(round(LARGHEZZA_PAGINA / pagina["w"] * 72)),
             "-jpeg", "-jpegopt", "quality=68,optimize=y", "-singlefile", str(percorso_pdf), str(uscita / nome_pagina)],
            capture_output=True, timeout=120, check=True)
        pagine[str(pagina["n"])] = f"{prefisso_url}/{nome_pagina}.jpg"
    return prodotti, pagine


if __name__ == "__main__":
    elenco, pagine_fatte = ritaglia_volantino(sys.argv[1], sys.argv[2], ".")
    (Path(sys.argv[2]) / "prodotti.json").write_text(json.dumps({"prodotti": elenco, "pagine": pagine_fatte}, ensure_ascii=False, indent=1), "utf-8")
    print(len(elenco), "prodotti")
