"""Lieux à découvrir pour Cimes : méthode nationale, à partir d'OpenStreetMap (+ Wikidata pour les photos).

Quatre familles :
  cime        sommets, cols, collines, belvédères (l'ADN de Cimes)
  nature      parcs et jardins notables, lacs, cascades, grottes, sites naturels
  patrimoine  forts, châteaux, tours, ruines, portes, sites archéologiques, monuments
  curiosite   attractions et curiosités locales reconnues

Filtrage qualitatif : un nom est obligatoire, et les catégories « bavardes » (mémoriaux, jardins,
attractions, fontaines, arbres) exigent en plus une fiche Wikidata, un classement patrimonial ou une taille
suffisante. On ne transforme pas chaque bâtiment ou chaque église en récompense.

Géométrie : les parcs et les lacs gardent un contour simplifié, pour que la découverte se fasse au bord
du site, pas à son centre. Sortie découpée en tuiles H3 (résolution 5) : l'appli ne charge que ce qui
entoure le joueur. Données © les contributeurs d'OpenStreetMap (ODbL) ; photos : Wikimedia Commons.
"""
import json, sys, os, math, re, time, datetime, collections, shutil, urllib.request, urllib.parse
import h3

src, outdir, region = sys.argv[1], sys.argv[2], sys.argv[3]
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
    if h == "archaeological_site": return "patrimoine", "site"
    if h == "monument": return "patrimoine", "monument"
    if h == "memorial" and wd: return "patrimoine", "monument"
    # nature
    if le in ("park", "garden") and (wd or area >= (5000 if le == "park" else 10000)): return "nature", "parc"
    if le == "nature_reserve" and (wd or area >= 50000): return "nature", "reserve"
    if n == "water" and t.get("water") not in ("river", "canal", "stream", "wastewater", "basin", "reflecting_pool") and (wd or area >= 20000): return "nature", "lac"
    if w == "waterfall" or n == "waterfall": return "nature", "cascade"
    if n == "cave_entrance": return "nature", "grotte"
    if n in ("arch", "rock", "stone", "gorge") and notable: return "nature", "site"
    if n == "tree" and (wd or t.get("denotation") == "natural_monument"): return "curiosite", "arbre"
    # curiosités
    if t.get("amenity") == "fountain" and (wd or h): return "curiosite", "fontaine"
    # petites curiosités locales sans fiche Wikidata : gardées si OSM les décrit comme lieu à voir (pas un commerce ni un bâtiment quelconque)
    if tr == "attraction" and (wd or t.get("heritage") or t.get("wikipedia") or t.get("description") or n or h or t.get("information") == "board"):
        return "curiosite", "curiosite"
    if tr == "attraction" and not t.get("shop") and not t.get("amenity") and not t.get("building"): return "curiosite", "curiosite"
    return None

rej = collections.Counter(); items = []
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line: continue
        g = json.loads(line); t = g.get("properties", {})
        nom = (t.get("name:fr") or t.get("name") or "").strip()
        if not nom: rej["sans nom"] += 1; continue
        if t.get("access") in NON: rej["accès privé"] += 1; continue
        oid = g.get("id")
        if not oid: rej["sans identifiant"] += 1; continue
        gm = geom(g.get("geometry") or {})
        if not gm: rej["géométrie"] += 1; continue
        la, lo, area, poly = gm
        wd = t.get("wikidata") if re.fullmatch(r"Q\d+", t.get("wikidata") or "") else None
        c = classer(t, area, wd)
        if not c: rej["pas assez notable"] += 1; continue
        e = {"id": str(oid), "n": nom, "f": c[0], "c": c[1], "lat": round(la, 6), "lon": round(lo, 6)}
        ele = num(t.get("ele"))
        if ele is not None and c[0] == "cime": e["ele"] = round(ele)
        if poly: e["poly"] = poly; e["ha"] = round(area / 1e4, 1)
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
print(f"Lieux retenus : {len(keep)} (doublons fusionnés : {dup})")
print("Écartés :", dict(rej))

# --- Wikidata : photo (P18) et courte description en français, par lots de 50 ---
ids = sorted({e["wd"] for e in keep if e.get("wd")}); WD = {}
UA = {"User-Agent": "CimesDonnees/1.0 (https://github.com/AntoineRnd/cimes-donnees)"}
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
print("Par type :"); [print(f"  {k:24s} {v}") for k, v in sorted(stats.items())]
if not keep: sys.exit("ERREUR : aucun lieu retenu.")
for k in tu:
    with open(f"{outdir}/{k}.json", encoding="utf-8") as f: assert json.load(f)["elements"]
print("Tuiles écrites et vérifiées :", len(tu))
