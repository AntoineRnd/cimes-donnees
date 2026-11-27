"""Transforme l'export OpenStreetMap (GeoJSON séquentiel) en un fichier léger pour Cimes.

Ne garde que les éléments NOMMÉS : sommets, cols, collines, belvédères.
Chaque élément : identifiant OSM, nom, catégorie, latitude, longitude, altitude si connue.
Données © les contributeurs d'OpenStreetMap, sous licence ODbL.
"""
import json, sys, datetime, collections, math

src, dst, region = sys.argv[1], sys.argv[2], sys.argv[3]
PRIO = {"sommet": 0, "col": 1, "colline": 2, "belvedere": 3}

def categorie(t):
    if t.get("natural") == "peak": return "sommet"
    if t.get("mountain_pass") == "yes" or t.get("natural") == "saddle": return "col"
    if t.get("natural") == "hill": return "colline"
    if t.get("tourism") == "viewpoint": return "belvedere"
    return None

def nom_cime(t):
    """Nom OSM réel ou libellé d'altitude explicite, jamais de nom géographique inventé."""
    cat = ("Sommet" if t.get("natural") == "peak" else
           "Col" if t.get("natural") == "saddle" or t.get("mountain_pass") == "yes" else None)
    if not cat: return None
    try: ele = float(str(t.get("ele", "")).replace(",", ".").replace("m", "").strip())
    except (ValueError, TypeError): return None
    if not math.isfinite(ele) or ele < 0 or ele > 9000: return None
    return f"{cat} sans nom · {round(ele)} m"

def altitude(t):
    try: return round(float(str(t.get("ele", "")).replace(",", ".").replace("m", "").strip()))
    except (ValueError, TypeError, OverflowError): return None

items, rejets = {}, collections.Counter()
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line: continue
        g = json.loads(line)
        if g.get("geometry", {}).get("type") != "Point": rejets["pas un point"] += 1; continue
        t = g.get("properties", {})
        nom = (t.get("name:fr") or t.get("name") or "").strip() or nom_cime(t)
        if not nom: rejets["sans nom"] += 1; continue
        cat = categorie(t)
        if not cat: rejets["catégorie inconnue"] += 1; continue
        if t.get("access") in ("private", "no"): rejets["accès privé"] += 1; continue
        lon, lat = g["geometry"]["coordinates"]
        oid = g.get("id")  # identifiant OSM (ex. « n123456 »), gardé pour les doublons et les mises à jour
        if not oid: rejets["sans identifiant OSM"] += 1; continue
        e = {"id": str(oid), "n": nom, "c": cat, "lat": round(lat, 6), "lon": round(lon, 6)}
        a = altitude(t)
        if a is not None: e["ele"] = a
        # dédoublonnage : un même point peut être à la fois sommet et belvédère -> on garde « sommet »
        k = e["id"]
        if k not in items or PRIO[cat] < PRIO[items[k]["c"]]: items[k] = e

L = sorted(items.values(), key=lambda e: (PRIO[e["c"]], e["n"]))
stats = collections.Counter(e["c"] for e in L)
print("Éléments retenus :", len(L), dict(stats))
print("Rejetés :", dict(rejets))
print("Par catégorie :")
for c in PRIO: print(f"  {c:10s} {stats.get(c, 0)}")
if not L:
    sys.exit("ERREUR : aucun élément retenu, le fichier n'est pas écrit.")
# Un nombre faible n'est pas une erreur : simple avertissement visible dans GitHub Actions.
if stats.get("sommet", 0) < 200 or len(L) < 500:
    print(f"::warning::Nombre de lieux plus faible que prévu ({len(L)} dont {stats.get('sommet', 0)} sommets). À vérifier.")
import os
os.makedirs(os.path.dirname(dst), exist_ok=True)
out = {"region": region, "genere": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
       "licence": "© les contributeurs d'OpenStreetMap, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
       "total": len(L), "par_categorie": dict(stats), "elements": L}
with open(dst, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
# Contrôle : le fichier écrit se relit, n'est pas vide et correspond au comptage.
with open(dst, encoding="utf-8") as f: chk = json.load(f)
assert chk["total"] == len(chk["elements"]) == len(L) > 0, "fichier incohérent"
assert len({e["id"] for e in chk["elements"]}) == len(L), "identifiants en double"
print("Fichier écrit et vérifié :", dst, os.path.getsize(dst), "octets")
