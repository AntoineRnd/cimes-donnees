"""Lieux à découvrir pour Cimes : méthode nationale, à partir d'OpenStreetMap (+ Wikidata pour les photos).

Quatre familles :
  cime        sommets, cols, collines, belvédères (l'ADN de Cimes)
  nature      parcs et jardins notables, lacs, cascades, grottes, sites naturels
  patrimoine  forts, châteaux, tours, ruines, portes, sites archéologiques, monuments
  curiosite   attractions et curiosités locales reconnues

Filtrage qualitatif (v3) : un nom est obligatoire, sauf pour le petit patrimoine rural (lavoir, chapelle, calvaire de
pierre, oratoire, moulin, mégalithe), gardé en lieu secondaire et dédoublonné par proximité ; les lieux de culte
gardent leur vraie étiquette et, s'ils ne sont pas classés, pas deux à moins de 1 km ; les curiosités suivent une liste explicite ; et les catégories « bavardes » (mémoriaux, jardins,
attractions, fontaines, arbres) exigent en plus une fiche Wikidata, un classement patrimonial ou une taille
suffisante. On ne transforme pas chaque bâtiment ou chaque église en récompense.

Géométrie : les parcs et les lacs gardent un contour simplifié, pour que la découverte se fasse au bord
du site, pas à son centre. Sortie découpée en tuiles H3 (résolution 5) : l'appli ne charge que ce qui
entoure le joueur. Données © les contributeurs d'OpenStreetMap (ODbL) ; photos : Wikimedia Commons.
"""
import json, sys, os, math, re, time, datetime, collections, shutil, urllib.request, urllib.parse
import h3

src, outdir, region = sys.argv[1], sys.argv[2], sys.argv[3]
UA = {"User-Agent": "CimesDonnees/1.0 (https://github.com/AntoineRnd/cimes-donnees)"}
TUILE = 5
NON = {"private", "no"}

def num(v):
    try: return float(str(v).replace(",", ".").replace("m", "").strip())
    except (ValueError, TypeError): return None

def ring_area_m2(ring):
    if len(ring) < 4: return 0.0
    la0 = sum(p[1] for p in ring) / len(ring); k = 111320 * math.cos(math.radians(la0))
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0] * k, ring[i][1] * 110540; x2, y2 = ring[i + 1][0] * k, ring[i + 1][1] * 110540
        s += x1 * y2 - x2 * y1
    return abs(s) / 2

def centroid(ring):
    xs = [p[0] for p in ring[:-1]] or [ring[0][0]]; ys = [p[1] for p in ring[:-1]] or [ring[0][1]]
    return sum(ys) / len(ys), sum(xs) / len(xs)

def simplify(ring, tol_m=20, maxpts=60):
    """Douglas-Peucker sur coordonnées projetées localement ; renvoie [[lat, lon], ...]."""
    if len(ring) <= 4: return [[round(p[1], 5), round(p[0], 5)] for p in ring]
    la0 = ring[0][1]; k = 111320 * math.cos(math.radians(la0))
    P = [(p[0] * k, p[1] * 110540) for p in ring]
    def dp(a, b, tol, out):
        (x1, y1), (x2, y2) = P[a], P[b]; dx, dy = x2 - x1, y2 - y1; L = dx * dx + dy * dy; best, bi = -1, -1
        for i in range(a + 1, b):
            x, y = P[i]; t = 0 if L == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L))
            d = math.hypot(x - x1 - t * dx, y - y1 - t * dy)
            if d > best: best, bi = d, i
        if best > tol: dp(a, bi, tol, out); out.append(bi); dp(bi, b, tol, out)
    tol = tol_m
    while True:
        keep = [0]; dp(0, len(P) - 1, tol, keep); keep.append(len(P) - 1); keep = sorted(set(keep))
        if len(keep) <= maxpts or tol > 500: break
        tol *= 1.6
    return [[round(ring[i][1], 5), round(ring[i][0], 5)] for i in keep]

def geom(g):
    """→ (lat, lon, aire m², contour simplifié ou None)"""
    t = g.get("type"); c = g.get("coordinates")
    if t == "Point": return c[1], c[0], 0, None
    if t == "LineString":
        m = c[len(c) // 2]; return m[1], m[0], 0, None
    rings = []
    if t == "Polygon": rings = [c[0]]
    elif t == "MultiPolygon": rings = [p[0] for p in c]
    elif t == "MultiLineString": m = c[0][len(c[0]) // 2]; return m[1], m[0], 0, None
    if not rings: return None
    r = max(rings, key=ring_area_m2); a = ring_area_m2(r); la, lo = centroid(r)
    return la, lo, a, (simplify(r) if a >= 3000 else None)

def classer(t, area, wd):
    """→ (famille, type) ou None. `notable` = fiche Wikidata, classement patrimonial ou attraction reconnue."""
    notable = bool(wd or t.get("heritage") or t.get("wikipedia") or t.get("tourism") == "attraction")
    n, h, mm, le, w, tr = t.get("natural"), t.get("historic"), t.get("man_made"), t.get("leisure"), t.get("waterway"), t.get("tourism")
    # cimes
    if n == "peak": return "cime", "sommet"
    if t.get("mountain_pass") == "yes" or n == "saddle": return "cime", "col"
    if n == "hill": return "cime", "colline"
    if tr == "viewpoint": return "cime", "belvedere"
    # patrimoine
    if h in ("fort",) or (h == "castle" and t.get("castle_type") in ("fortress", "defensive", "citadel")): return "patrimoine", "fort"
    if h in ("castle", "manor"): return "patrimoine", "chateau"
    if h == "ruins": return "patrimoine", "ruines"
    if h == "tower" or (mm == "tower" and (h or notable) and t.get("tower:type") not in ("communication", "cooling", "lighting")): return "patrimoine", "tour"
    if h in ("city_gate", "citywalls"): return "patrimoine", "porte"
    if h in ("archaeological_site", "megalith", "standing_stone"): return "patrimoine", "site"
    if h == "monument": return "patrimoine", "monument"
    if h == "memorial" and wd and t.get("memorial") not in ("statue", "bust", "plaque", "stolperstein", "stele", "blue_plaque"): return "patrimoine", "monument"
    # nature
    # parcs : pas les petits squares de quartier (1 ha au moins, ou 0,3 ha avec une fiche Wikidata)
    if le in ("park", "garden") and (area >= 10000 or (wd and area >= 3000)): return "nature", "parc"
    if le == "nature_reserve" and (wd or area >= 50000): return "nature", "reserve"
    if n == "water" and t.get("water") not in ("river", "canal", "stream", "wastewater", "basin", "reflecting_pool") and (wd or area >= 20000): return "nature", "lac"
    if w == "waterfall" or n == "waterfall": return "nature", "cascade"
    if n == "cave_entrance": return "nature", "grotte"
    if n in ("arch", "rock", "stone", "gorge") and notable: return "nature", "site"
    if n == "tree" and (wd or t.get("denotation") == "natural_monument"): return "curiosite", "arbre"
    # patrimoine des villages (v2) : de vraies découvertes, présentes partout en France, mais filtrées.
    # Elles comptent comme les autres lieux (barème inchangé) ; « mineur » sert seulement à les afficher plus discrètement.
    nm = (t.get("name:fr") or t.get("name") or "").lower()
    if t.get("amenity") == "place_of_worship" or h in ("church", "chapel") or t.get("building") == "chapel":
        if "chapelle" in nm or t.get("building") == "chapel" or h == "chapel": return "patrimoine", "chapelle"
        typ = culte(t, nm)
        if classe(t): return "patrimoine", typ                       # monument historique : toujours gardé
        # non classé : gardé s'il a un intérêt patrimonial identifiable (fiche Wikidata + article, photo ou date ancienne),
        # puis limité en ville à un seul par secteur (voir plus bas) pour éviter « une église à chaque rue »
        # (essai 2 : exiger en plus un article ou une photo retirait les églises de village, trop strict)
        if wd or ancien(t): return "patrimoine", typ
        return None
    if t.get("amenity") == "lavoir" or t.get("building") == "lavoir": return "patrimoine", "lavoir"
    if mm in ("windmill", "watermill") or h in ("windmill", "watermill"): return "patrimoine", "moulin"
    if h == "wayside_shrine": return "patrimoine", "oratoire"
    if h == "wayside_cross":                                 # croix : seulement les calvaires remarquables
        if notable or "calvaire" in nm or t.get("heritage"): return "patrimoine", "calvaire"
        return None
    if h == "bridge" or (t.get("bridge") and (t.get("heritage") or (wd and h))): return "patrimoine", "pont"
    if n == "spring": return "nature", "source"
    # curiosités
    if t.get("amenity") == "fountain" and (wd or h): return "curiosite", "fontaine"
    # petites curiosités locales sans fiche Wikidata : gardées si OSM les décrit comme lieu à voir (pas un commerce ni un bâtiment quelconque)
    # pas les enclos de zoo ni les manèges
    if tr == "attraction":
        # une fiche Wikidata ou une description ne suffit pas : un bar, une borne ou un immeuble restent sans intérêt.
        # On garde seulement ce qui relève d'une catégorie « à voir » explicite.
        if t.get("attraction") in MANEGES or t.get("zoo"): return None
        if any(t.get(k) for k in BANAL) or t.get("amenity") not in (None, "fountain"): return None
        if t.get("building") and t.get("building") not in BAT_OK: return None
        if t.get("leisure") in ("playground", "pitch", "sports_centre", "fitness_station", "track", "water_park"): return None
        if h or n or mm in MM_OK or classe(t) or MOTS.search(nm): return "curiosite", "curiosite"
        return None
    return None

MANEGES = {"animal", "amusement_ride", "carousel", "roller_coaster", "train", "water_slide", "bumper_car", "swing_carousel", "kiddie_ride", "dark_ride", "log_flume", "drop_tower", "pirate_ship", "maze"}
BANAL = ("shop", "office", "craft", "highway", "railway", "public_transport", "healthcare", "club", "sport", "aeroway", "power", "advertising", "brand")
BAT_OK = {"church", "chapel", "castle", "tower", "ruins", "windmill", "watermill", "lavoir", "bridge", "monument", "temple", "shrine", "yes"}
MM_OK = {"lighthouse", "tower", "obelisk", "windmill", "watermill", "bridge", "adit", "kiln", "mineshaft", "water_well"}
MOTS = re.compile(r"rocher|roche|pierre|grotte|gouffre|chaos|marmite|cascade|fontaine|puits|lavoir|four [àa] pain|cadran|statue|g[ée]ant|arbre|ch[êe]ne|tilleul|\bif\b|dolmen|menhir|cromlech|vestige|ruine|belv[ée]d|panorama|point de vue|table d.orientation|labyrinthe|tunnel|aqueduc|viaduc|[ée]cluse|phare|moulin|rempart|calvaire|oratoire|chapelle|clo[îi]tre|crypte|souterrain|carri[èe]re|mine\b|ermitage|source|cirque|falaise|gorges?|canyon|[ée]tang|marais|tourbi[èe]re|jardin|kiosque|lavoir|halle|beffroi|horloge|cadran", re.I)

def classe(t):
    """monument historique ou patrimoine protégé"""
    return bool(t.get("heritage") or t.get("ref:mhs") or t.get("heritage:operator") or t.get("mhs:inscription_date"))

def ancien(t):
    m = re.match(r"~?(\d{3,4})", str(t.get("start_date") or ""))
    return bool(m and int(m.group(1)) < 1900)

def culte(t, nm):
    """bonne étiquette : église, temple, synagogue, mosquée"""
    rel, den = t.get("religion"), (t.get("denomination") or "").lower()
    if rel == "jewish" or "synagogue" in nm: return "synagogue"
    if rel == "muslim" or "mosqu" in nm: return "mosquee"
    if rel in ("buddhist", "hindu", "sikh", "taoist", "shinto") or "pagode" in nm: return "temple"
    if den in ("protestant", "reformed", "lutheran", "evangelical", "calvinist", "methodist", "baptist") or nm.startswith("temple"): return "temple"
    return "eglise"

RURAL = {"lavoir", "chapelle", "calvaire", "oratoire", "moulin"}
CULTE = {"eglise", "temple", "synagogue", "mosquee"}
MEGA = re.compile(r"^(menhir|dolmen|cromlech|all[ée]e couverte|m[ée]galithe)s?$", re.I)
def rural_sans_nom(t):
    """nom par défaut pour le petit patrimoine sans nom propre ; None = on n'en fait pas une découverte"""
    h, mm, b = t.get("historic"), t.get("man_made"), t.get("building")
    if t.get("access") in NON: return None
    if t.get("amenity") == "lavoir" or b == "lavoir": return "Lavoir"
    if b == "chapel" or h == "chapel": return "Chapelle"
    if mm in ("windmill", "watermill") or h in ("windmill", "watermill"):
        if (t.get("ruins") == "yes" or t.get("disused") == "yes") and not classe(t): return None
        return "Moulin"
    if h == "wayside_shrine": return "Oratoire"
    # croix sans nom : très nombreuses le long des routes ; seulement les calvaires de pierre ou protégés
    if h == "wayside_cross" and (classe(t) or t.get("material") in ("stone", "granite", "sandstone", "limestone")): return "Calvaire"
    if h in ("archaeological_site", "megalith", "standing_stone") and (t.get("site_type") == "megalith" or h != "archaeological_site"):
        mt = (t.get("megalith_type") or "").lower()
        return {"dolmen": "Dolmen", "passage_grave": "Allée couverte", "gallery_grave": "Allée couverte", "stone_circle": "Cromlech"}.get(mt, "Menhir")
    return None

BANAL_NOM = re.compile(r"^(maisons?|immeubles?|b[âa]timents?|hangars?|fermes?|logis|terrain\b.*|pelouse\b.*|maison d'habitation|ensemble immobilier)$", re.I)
GENERIQUE = re.compile(r"^(monuments? aux morts.*|ruines?|vestiges?|parcours de sant[ée]|aire de jeux.*|square|jardin|parc|fontaine|lavoir|calvaire|croix|tour|ch[âa]teau|chapelle|[ée]glise|moulin|source|pont|oratoire|croix de mission|vieux pont)$", re.I)
rej = collections.Counter(); items = []
EX = collections.defaultdict(list)   # exemples écartés, pour vérifier ce que les filtres retirent
def ecarte(raison, nom, la, lo, t):
    rej[raison] += 1
    if nom and len(EX[raison]) < 400: EX[raison].append({"n": nom, "lat": round(la, 5), "lon": round(lo, 5), "tags": {k: v for k, v in t.items() if k in ("amenity", "historic", "man_made", "natural", "leisure", "tourism", "heritage", "building", "water")}})
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line: continue
        g = json.loads(line); t = g.get("properties", {})
        nom = (t.get("name:fr") or t.get("name") or "").strip()
        sansnom = not nom
        if sansnom:
            nom = rural_sans_nom(t)
            if not nom: rej["sans nom"] += 1; continue
            t = dict(t, name=nom)
        if t.get("access") in NON: rej["accès privé"] += 1; continue
        oid = g.get("id")
        if not oid: rej["sans identifiant"] += 1; continue
        gm = geom(g.get("geometry") or {})
        if not gm: rej["géométrie"] += 1; continue
        la, lo, area, poly = gm
        wd = t.get("wikidata") if re.fullmatch(r"Q\d+", t.get("wikidata") or "") else None
        c = classer(t, area, wd)
        if not c: ecarte("pas assez notable", nom, la, lo, t); continue
        # noms génériques sans fiche : un « Monument aux morts » ou une « Ruine » par village n'est pas une découverte
        # … sauf le petit patrimoine rural (lavoir, chapelle, calvaire, oratoire, moulin, menhir) : gardé en lieu secondaire,
        # puis dédoublonné par proximité plus bas
        rural = c[1] in RURAL or (c[1] == "site" and MEGA.match(nom))
        if not wd and GENERIQUE.match(nom) and c[0] != "cime" and not rural: ecarte("nom générique", nom, la, lo, t); continue
        # « Immeuble », « Maisons », « Terrain 26 » : même avec une fiche (immeubles inscrits de Lille), ce n'est pas une découverte
        if BANAL_NOM.match(nom): ecarte("nom banal (immeuble, maison, terrain…)", nom, la, lo, t); continue
        if not wd and (nom[0].islower() or re.match(r"(aire|plaine|terrain|espace) de jeux|city[ -]?stade", nom, re.I)): rej["nom vague ou aire de jeux"] += 1; continue
        # un plan d'eau trop petit (bassin, fontaine) n'est pas un lac, même avec une fiche
        if c[1] == "lac" and area < 5000: rej["bassin trop petit"] += 1; continue
        e = {"id": str(oid), "n": nom, "f": c[0], "c": c[1], "lat": round(la, 6), "lon": round(lo, 6)}
        ele = num(t.get("ele"))
        if ele is not None and c[0] == "cime": e["ele"] = round(ele)
        if poly: e["poly"] = poly; e["ha"] = round(area / 1e4, 1)
        if rural and not wd and (sansnom or GENERIQUE.match(nom)): e["_gen"] = 1      # lieu rural au nom générique
        if c[1] in CULTE and not classe(t): e["_cnc"] = 1 if t.get("wikipedia") else 2  # lieu de culte non classé (1 = avec article)
        if wd: e["wd"] = wd
        com = t.get("wikimedia_commons") or ""
        if com.startswith("File:"): e["img"] = com[5:]
        items.append(e)

# --- doublons : même fiche Wikidata, ou même nom à moins de 400 m (on garde la version avec contour) ---
PRIO = {"cime": 0, "patrimoine": 1, "nature": 2, "curiosite": 3}
def norm(s): return re.sub(r"[^a-z0-9]", "", s.lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace("â", "a").replace("ô", "o").replace("î", "i").replace("ç", "c"))
def d(a, b): return math.hypot((a["lon"] - b["lon"]) * 111320 * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * 110540)
items.sort(key=lambda e: (PRIO[e["f"]], -("poly" in e), -("wd" in e)))
keep, bywd, byname = [], {}, collections.defaultdict(list); dup = 0
def fusion(o, e):
    """garde un seul lieu, en récupérant ce qui manque (contour, fiche Wikidata, photo)"""
    for k in ("poly", "ha", "wd", "img", "ele"):
        if e.get(k) is not None and o.get(k) is None: o[k] = e[k]
    if o.get("wd"): bywd[o["wd"]] = o
for e in items:
    o = bywd.get(e.get("wd")) if e.get("wd") else None
    if o is None: o = next((x for x in byname[norm(e["n"])] if d(e, x) < 400), None)
    if o is not None: dup += 1; fusion(o, e); continue
    keep.append(e); byname[norm(e["n"])].append(e)
    if e.get("wd"): bywd[e["wd"]] = e
# étangs et lacs sans fiche Wikidata : un seul (le plus grand) par secteur H3 de résolution 7 (≈ 5 km²),
# pour que la Dombes ou la Sologne ne deviennent pas 130 découvertes « étang » ; ceux avec une fiche restent tous
lacs = collections.defaultdict(list)
for e in keep:
    if e["c"] == "lac" and not e.get("wd"): lacs[h3.latlng_to_cell(e["lat"], e["lon"], 7)].append(e)
trop = set()
for L in lacs.values():
    L.sort(key=lambda e: -e.get("ha", 0)); trop.update(id(e) for e in L[1:])
for L in lacs.values():
    for e in L[1:]: ecarte("étang secondaire du même secteur", e["n"], e["lat"], e["lon"], {"ha": e.get("ha")})
keep = [e for e in keep if id(e) not in trop]
# petit patrimoine au nom générique : pas quinze croix pour une même route. Un seul lieu du même type
# dans un rayon donné (on garde celui qui a une photo). Pas de quota par commune.
ECART = {"calvaire": 2500, "oratoire": 2500, "lavoir": 700, "chapelle": 700, "moulin": 700, "site": 500}
gen = sorted([e for e in keep if e.get("_gen")], key=lambda e: -("img" in e))
vus = collections.defaultdict(list); trop = set()
for e in gen:
    k = e["c"]; r = ECART.get(k, 700)
    if any(d(e, o) < r for o in vus[k]): trop.add(id(e)); ecarte(f"{k} générique trop proche d'un autre", e["n"], e["lat"], e["lon"], {}); continue
    vus[k].append(e)
keep = [e for e in keep if id(e) not in trop]
# lieux de culte non classés : pas de quota par secteur (deux villages voisins gardent chacun leur église).
# On retire seulement un lieu du même type à moins de 1 km d'un autre déjà gardé (le mieux documenté passe d'abord) :
# le village garde son église, la ville n'en affiche pas une par rue. Les monuments historiques restent tous.
cand = sorted([e for e in keep if e.get("_cnc")], key=lambda e: (e["_cnc"], -("img" in e)))
grille = collections.defaultdict(list); trop = set()
for e in cand:
    cl = h3.latlng_to_cell(e["lat"], e["lon"], 7)
    if any(o["c"] == e["c"] and d(e, o) < 1000 for n in h3.grid_disk(cl, 1) for o in grille[n]):
        trop.add(id(e)); ecarte("lieu de culte non classé à moins de 1 km d'un autre", e["n"], e["lat"], e["lon"], {}); continue
    grille[cl].append(e)
keep = [e for e in keep if id(e) not in trop]
MINEUR = {"lavoir", "calvaire", "oratoire", "source", "moulin", "chapelle", "pont"}
for e in keep:
    if (e["c"] in MINEUR or e.get("_gen")) and not e.get("wd"): e["m"] = 1
    e.pop("_gen", None); e.pop("_cnc", None)
print(f"Lieux retenus : {len(keep)} (doublons fusionnés : {dup})")
print("Écartés :", dict(rej))

# --- points hauts : un fort, une tour, une chapelle… perché sur une butte devient une « cime » (ex. la Bastille à Grenoble) ---
#     Altitudes : Terrain Tiles (Mapzen / AWS, domaine public), zoom 12 (≈ 27 m par pixel en France).
#     Règle : le lieu est presque au sommet de sa butte (à 50 m près dans un rayon de 300 m)
#             ET domine les alentours d'au moins 80 m dans un rayon de 1,5 km.
import io
try:
    from PIL import Image
except ImportError:
    Image = None
DEMZ, DEMC = 12, {}
def dem(lat, lon):
    n = 2 ** DEMZ; x = (lon + 180) / 360 * n; y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    tx, ty = int(x), int(y); k = (tx, ty)
    if k not in DEMC:
        try:
            u = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{DEMZ}/{tx}/{ty}.png"
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r: DEMC[k] = Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception: DEMC[k] = None
    im = DEMC[k]
    if im is None: return None
    R, G, B = im.getpixel((min(255, int((x - tx) * 256)), min(255, int((y - ty) * 256))))
    return R * 256 + G + B / 256 - 32768
def autour(lat, lon, r, n):
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n; out.append(dem(lat + r * math.cos(a) / 110540, lon + r * math.sin(a) / (111320 * math.cos(math.radians(lat)))))
    return [v for v in out if v is not None]
HAUT = {"fort", "chateau", "ruines", "tour", "site", "porte", "chapelle"}  # pas les monuments aux morts ni les attractions
nh = 0
if Image is None: print("::warning::Pillow absent : détection des points hauts désactivée")
else:
    for e in keep:
        if e["f"] == "cime" or e["c"] not in HAUT: continue
        z0 = dem(e["lat"], e["lon"])
        if z0 is None: continue
        near = autour(e["lat"], e["lon"], 150, 8) + autour(e["lat"], e["lon"], 300, 12)
        far = autour(e["lat"], e["lon"], 700, 12) + autour(e["lat"], e["lon"], 1500, 16)
        if not near or not far: continue
        if max(near) - z0 <= 50 and z0 - min(far) >= 80:
            e["haut"] = round(z0 - min(far)); e["ele"] = round(z0); e["orig"] = e["f"]; e["f"] = "cime"; nh += 1
    # une seule cime par butte : sur une même colline (ex. Fourvière), on garde le point haut le plus marquant,
    # les autres restent dans leur famille d'origine ; et pas de doublon avec un vrai sommet tout proche
    H = sorted([e for e in keep if e.get("haut")], key=lambda e: (-(1 if e.get("wd") else 0), -e["haut"], -e["ele"]))
    pics = [e for e in keep if e["f"] == "cime" and not e.get("haut") and e["c"] in ("sommet", "colline")]
    gardes = []
    for e in H:
        if any(d(e, o) < 800 for o in gardes) or any(d(e, o) < 300 for o in pics):
            e["f"] = e.pop("orig"); e.pop("haut"); nh -= 1; continue
        gardes.append(e)
    print(f"Points hauts devenus des cimes : {nh} (une par butte) · tuiles d'altitude lues : {len(DEMC)}")

# --- Wikidata : photo (P18) et courte description en français, par lots de 50 ---
ids = sorted({e["wd"] for e in keep if e.get("wd")}); WD = {}
for i in range(0, len(ids), 50):
    q = "|".join(ids[i:i + 50])
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": q, "props": "claims|descriptions", "languages": "fr", "format": "json"})
    for essai in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r: data = json.load(r)
            for qid, ent in (data.get("entities") or {}).items():
                img = None
                try: img = ent["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"]
                except (KeyError, IndexError, TypeError): pass
                desc = ((ent.get("descriptions") or {}).get("fr") or {}).get("value")
                WD[qid] = (img, desc)
            break
        except Exception as ex:
            if essai == 2: print(f"::warning::Wikidata indisponible pour un lot ({ex})")
            time.sleep(3)
    time.sleep(0.3)
nimg = 0
for e in keep:
    if e.get("wd") in WD:
        img, desc = WD[e["wd"]]
        if img and not e.get("img"): e["img"] = img
        if desc: e["desc"] = desc[:140]
    if e.get("img"): nimg += 1
print(f"Fiches Wikidata : {len(ids)} · avec photo : {nimg}")

# --- tuiles ---
shutil.rmtree(outdir, ignore_errors=True); os.makedirs(outdir, exist_ok=True)
tu = collections.defaultdict(list)
for e in keep: tu[h3.latlng_to_cell(e["lat"], e["lon"], TUILE)].append(e)
for k, L in tu.items():
    with open(f"{outdir}/{k}.json", "w", encoding="utf-8") as f: json.dump({"elements": L}, f, ensure_ascii=False, separators=(",", ":"))
stats = collections.Counter(f'{e["f"]}/{e["c"]}' for e in keep)
idx = {"region": region, "version": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "tuile_res": TUILE, "total": len(keep),
       "par_type": dict(sorted(stats.items())), "tuiles": sorted(tu),
       "licence": "Lieux © contributeurs OpenStreetMap, ODbL 1.0 ; descriptions Wikidata (CC0) ; photos Wikimedia Commons (licence propre à chaque photo)"}
with open(f"{outdir}/index.json", "w", encoding="utf-8") as f: json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
with open(f"{outdir}/../ecartes.json", "w", encoding="utf-8") as f: json.dump({"comptes": dict(rej), "exemples": EX}, f, ensure_ascii=False, separators=(",", ":"))
print("Par type :"); [print(f"  {k:24s} {v}") for k, v in sorted(stats.items())]
if not keep: sys.exit("ERREUR : aucun lieu retenu.")
for k in tu:
    with open(f"{outdir}/{k}.json", encoding="utf-8") as f: assert json.load(f)["elements"]
print("Tuiles écrites et vérifiées :", len(tu))
