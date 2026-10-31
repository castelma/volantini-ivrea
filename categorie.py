#!/usr/bin/env python3
"""A che categoria appartiene un prodotto, dal nome. Vince la prima regola che trova una parola.

L'ordine conta: «cioccolato al latte» deve fermarsi ai dolci prima di arrivare al latte,
«pasta all'uovo» alla pasta prima delle uova, «focaccia con olio» al pane prima del condimento.
"""
import re
import unicodedata

REGOLE = [
    ("Animali", r"\b(cane|cani|gatto|gatti|gattini|cat|dog|pet|catsan|lettiera|purina|felix|gourmet (gold|perle)|friskies|sheba|whiskas|cesar|pedigree|almo nature|crocchette|cibo per|petfriends)\b"),
    ("Bambini", r"(pannolin|omogeneizz|biberon|plasmon|mellin|huggies|pampers|neonat|prima infanzia)"),
    ("Igiene e bellezza", r"(skinactive|maschera tessuto|bagno schiuma|shampoo|bagnoschiuma|bagnodoccia|\bdoccia\b|deodorant|dentifric|spazzolin|collutorio|assorbent|salvaslip|proteggislip|rasoi|schiuma da barba|gillette|sapone|detergente intimo|crema (viso|corpo|mani|fluida)|balsamo|\btinta\b|colorazione|cotton fioc|struccant|kaloderma|nivea|dopobarba|garnier|pantene|l.oreal|cura del corpo|maschera per)"),
    ("Casa e pulizia", r"(\bdetergent[ei]\b|igienica|bobina|strappi|domopak|carta forno|vaschette|\bsacchi\b|gel piatti|additiv|detersiv|lavatrice|lavastoviglie|ammorbident|candeggin|sgrassat|pavimenti|anticalcare|bucato|napisan|disinfettante|spugn|carta igienica|carta casa|asciugatutto|tovaglioli|fazzoletti|scottex|\brotoli\b|sacchetti|pellicola|\bscopa\b|mocio|panni?\b|insetticid|dixan|\bdash\b|ariel|\bfinish\b|svelto|vileda|foxy|lysoform|profumatori|piatti fondi|batterie|\bpile\b|\bwc\b|omino bianco)"),
    ("Altro", r"(\bvaso\b|\bpigiam|asciugamani|lenzuol|completo letto|padell|pentol|friggitrice|\btv\b|televisor|smartphone|tablet|aspirapolvere|forno a microonde|ciclamin|orchide|piant[ae]\b|stella di natale|addobb|\balbero\b|centrotavola|prolung|adattator|lampad)"),
    ("Surgelati", r"(surgelat|findus|orogel|sofficini|bastoncini|quattro salti|4 salti|\bgelat[oi]\b|cornetto|magnum|algida|sammontana|\bfrosta\b|bonduelle|green frost)"),
    ("Vino e birra", r"(d\.o\.c|i\.g\.t|\d+.?°c|baileys|irish cream|limoncello|keglevich|select bitter|\bvino\b|\bvini\b|\bdoc\b|\bdocg\b|\bigt\b|spumante|prosecco|champagne|franciacorta|birra|ichnusa|moretti|heineken|peroni|menabrea|nastro azzurro|\bamaro\b|liquore|grappa|whisky|\bgin\b|vodka|\brum\b|\bbrut\b|barbera|nebbiolo|ortrugo|bonarda|novello|chianti|montepulciano|primitivo|pinot|chardonnay|sauvignon|vermentino|lambrusco|gutturnio|moscato|sangiovese|merlot|cabernet|aperol|campari|spritz)"),
    ("Acqua e bibite", r"(cedrata|tassoni|monster|\bthe\b.*freddo|\bacqua\b|bibit|aranciata|\bcola\b|\bcoca\b|pepsi|\bfanta\b|\bsprite\b|\bsucc[oh]i?\b|\bbevanda\b|skipper|estathe|the freddo|energy|red bull|sanpellegrino|ferrarelle|levissima|\blete\b|isotonic)"),
    ("Pesce", r"(fritto misto|salmone(?!.*(scatola))|merluzzo|\borat[ae]\b|branzin|spigol|gamber|mazzancoll|polpo|polipo|seppi|calamar|totan|cozze|vongol|ostrich|\bpesce\b|baccala|stoccafisso|\btrota\b|platessa|sogliola|nasello|halibut|surimi|crostacei|ricciola|pescheria|tonno (a pinne|fresco)|trancio di tonno)"),
    ("Salumi", r"(cotechino|zampone|guanciale|\bcrudo\b|prosciutt|\bsalam|mortadell|\bspeck\b|bresaol|pancett|wurstel|wuber|wudy|\bcoppa\b|culatello|\blardo\b|nduja|affettat|cubetti di cotto|\bcotto\b|backon)"),
    ("Pane, pizza e pronti", r"(\bpane\b|\bpan\b|pancarre|panini|piadin|\bpiada\b|granpiada|focacc|cracker|grissin|taralli|schiacciatin|friselle|pinsa|pangrattato|crostini|\bpizza\b|\bpizze\b|sandwich|piatt[oi] pront|piatto bilanciato|\bpronto\b|\bpronti\b|take away|insalatona|\bpoke\b|sushi|gastronomia|le gioiose|kebab|hummus|chicken salad)"),
    ("Colazione e caffè", r"(digestives|cappuccino|nescafe|biscott|frollin|cereali|muesli|fette biscottate|marmellat|confettur|croissant|brioche|plumcake|mulino bianco|saiwa|pavesi|oreo|ringo|rice krispies|kellogg|nesquik|ovomaltina|caffe|capsule|nespresso|lavazza|illy|vergnano|segafredo|kimbo|borbone|\bthe\b|tisan|camomill|infus|zucchero|dolcificant|\bmiele\b|nutella)"),
    ("Dolci e snack", r"(torroncin|marrons|glaces|chupa chups|tartufi|witor|fruit.?tella|pernigotti|merendin|merenda|cioccolat|praline|tavolett|cacao|caramell|torrone|panettone|pandoro|colomba|\btort[ae]\b|krapfen|wafer|kinder|ferrero|lindt|novi\b|nocciolato|perugina|\bbaci\b|mon cheri|pocket coffee|bueno|kit ?kat|snickers|\bmars\b|twix|haribo|crostat|budin|muu muu|patatine|\bchips\b|pringles|san carlo|\bsnack\b|salatini|popcorn|tiramisu|cunesi|cuneesi|donuts|candy|halloween|novellino|fulfil)"),
    ("Olio, sughi e conserve", r"(\bsals[ae]\b|mutti|\bolio\b|extra ?vergine|\baceto\b|\bsale\b|passata|pelati|polpa (di pomodoro|finissima)|concentrato di pomodoro|\bsugo\b|\bsughi\b|\bragu\b|\bpesto\b|maionese|ketchup|senape|lenticch|\bceci\b|fagioli\b|piselli|\bmais\b|legumi|\bzupp[ae]\b|minestra|\bbrodo\b|\bdado\b|spezie|sottoli|sott.?olio|grigliati|\bolive\b|capperi|\bsemi\b|\btonno\b|rio ?mare|asdomar|nostromo|mareblu|consorcio|angelo parodi|callipo|sgombro|acciugh|sardine)"),
    ("Pasta, riso e farina", r"(ravioles|\bpasta\b|spaghett|\bpenne\b|fusill|rigaton|maccheron|farfalle|lasagn|cannellon|gnocch|tortellin|ravioli|agnolott|cappellett|tagliatell|pappardell|tagliolin|orecchiett|trofie|sfoglia|passatelli|\briso\b|risotto|carnaroli|arborio|basmati|farina|cous ?cous|polenta|noodle|\bsoba\b|lievito|semola|barilla|de cecco|rummo|garofalo|voiello|mosconi|ronzoni)"),
    ("Carne", r"(maialino|pollo|tacchin|bovin|suino|vitello|manzo|maiale|hamburger|burger|salsicc|macinat|cosci[ae]|cosce|\bpetto\b|fettine|arrosto|spezzatino|costine|costata|bistecc|agnello|coniglio|\bcarne\b|lonza|scaloppin|cordon bleu|cotolett|straccetti|polpett|\bfesa\b|sovracosce|alette|roastbeef|bocconcini di|braciol|tagliata|battuta|medaglioni|filetto di)"),
    ("Latte, formaggi e uova", r"(provolone|raschera|caciocavallo|sottilette|butter|president\b|\blatte\b|yogurt|kefir|\bburro\b|\bpanna\b|mascarpone|mozzarell|formagg|\bgrana\b|parmigian|reggiano|pecorino|ri[c]+otta|ricottine|robiola|stracchin|crescenza|gorgonzola|taleggio|fontina|\btoma\b|provola|scamorza|asiago|emmental|leerdammer|philadelphia|camoscio|\bbrie\b|bufala|actimel|activia|danone|muller|granarolo|parmalat|zymil|arborea|\buova\b|\buovo\b|skyr|burrata|primo sale|spicchio gran|biraghi)"),
    ("Frutta", r"(\bmel[ae]\b|\bper[ae]\b|banan|aranc[ei]|clementin|mandarin|kiwi|\buva\b|ananas|limon[ei]|pompelm|fragol|mirtill|lampon|melogran|\bcach[ie]\b|avocado|castagn|marroni|\bmango\b|papaya|\bfrutta\b|\bnoci\b|mandorl|nocciol|pistacch|anacardi|arachid|uvetta|datteri|prugne|\bfichi\b)"),
    ("Verdura", r"(insalat|lattug|misticanz|rucola|spinaci|zucchin|melanzan|peperon|pomodor|carot|patat|cipoll|\baglio\b|broccol|cavol|verza|finocch|fungh|zucca|sedano|radicchio|bietol|fagiolin|carciof|asparag|porri\b|verdur|catalogna|cicoria|songino|valeriana|barbabietol|minestrone)"),
]
REGOLE = [(nome, re.compile(schema)) for nome, schema in REGOLE]
ALTRO = "Altro"
ORDINE = ["Frutta", "Verdura", "Carne", "Pesce", "Salumi", "Latte, formaggi e uova", "Pane, pizza e pronti", "Pasta, riso e farina",
          "Olio, sughi e conserve", "Surgelati", "Colazione e caffè", "Dolci e snack", "Acqua e bibite", "Vino e birra",
          "Casa e pulizia", "Igiene e bellezza", "Bambini", "Animali", ALTRO]


SENZA_NOME = "Senza nome"
_PRONTI, _CONSERVE, _COLAZIONE, _DOLCI, _LATTE, _PASTA = ("Pane, pizza e pronti", "Olio, sughi e conserve", "Colazione e caffè",
                                                          "Dolci e snack", "Latte, formaggi e uova", "Pasta, riso e farina")
# Categoria ufficiale Carrefour -> quelle nostre che ci stanno dentro, e quella da usare se il nome non ne indica una
CARREFOUR = {
    "carne e pesce": ({"Carne", "Pesce", _PRONTI}, "Carne"),
    "gastronomia e panetteria": ({_PRONTI, "Salumi", _LATTE, _PASTA, "Carne", "Pesce", _COLAZIONE, _DOLCI, "Verdura", _CONSERVE}, _PRONTI),
    "salumi e formaggi": ({"Salumi", _LATTE}, "Salumi"),
    "freschi confezionati": ({_LATTE, _PASTA, "Salumi", _PRONTI, _COLAZIONE, _DOLCI, _CONSERVE, "Carne", "Pesce"}, _LATTE),
    "ortofrutta": ({"Frutta", "Verdura"}, "Verdura"),
    "dispensa": ({_CONSERVE, _PASTA, _COLAZIONE, _DOLCI, _PRONTI, "Frutta", "Verdura"}, _CONSERVE),
    "surgelati": ({"Surgelati"}, "Surgelati"),
    "colazione": ({_COLAZIONE, _DOLCI, _LATTE, _PRONTI}, _COLAZIONE),
    "acque e bevande": ({"Acqua e bibite", "Vino e birra"}, "Acqua e bibite"),
    "cura persona": ({"Igiene e bellezza", "Casa e pulizia"}, "Igiene e bellezza"),
    "cura della casa": ({"Casa e pulizia", "Igiene e bellezza"}, "Casa e pulizia"),
    "mondo baby": ({"Bambini"}, "Bambini"),
    "mondo pet": ({"Animali"}, "Animali"),
    "bazar": ({ALTRO, "Casa e pulizia", "Animali"}, ALTRO),
    "tessile e abbigliamento": ({ALTRO}, ALTRO),
    "elettronica": ({ALTRO}, ALTRO),
}


def categoria_carrefour(nome, etichetta):
    """Il nome dice quale, l'etichetta ufficiale fa da guardia: se non torna, vale l'etichetta."""
    nostra = categoria(nome)
    regola = CARREFOUR.get((etichetta or "").lower())
    if not regola:
        return nostra
    return nostra if nostra in regola[0] else regola[1]


def normale(testo):
    senza = unicodedata.normalize("NFD", testo)
    return "".join(c for c in senza if not unicodedata.combining(c)).lower().replace("’", "'")


def categoria(nome):
    pulito = normale(nome)
    for titolo, schema in REGOLE:
        if schema.search(pulito):
            return titolo
    return ALTRO
