"""Unit tests for catalogue rules without downloading OSM or contacting Wikidata."""
import ast, math, re
from pathlib import Path
source = Path(__file__).with_name("lieux.py").read_text()
tree = ast.parse(source)
names = {"nom_cime", "classer", "classe", "ancien", "culte"}
constants = {"MANEGES", "BANAL", "BAT_OK", "MM_OK", "MOTS"}
selected = [node for node in tree.body if (isinstance(node, ast.FunctionDef) and node.name in names) or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets))]
env = {"math": math, "re": re}
exec(compile(ast.Module(body=selected, type_ignores=[]), "<selection>", "exec"), env)
c, nom = env["classer"], env["nom_cime"]
assert c({"natural":"peak"}, 0, None) == ("cime","sommet")
assert c({"mountain_pass":"yes"}, 0, None) == ("cime","col")
assert nom({"natural":"peak","ele":"1920"}) == "Sommet sans nom · 1920 m"
assert nom({"natural":"peak"}) is None
assert nom({"natural":"peak","ele":"nan"}) is None
assert c({"leisure":"park"}, 5000, None) == ("nature","parc")
assert c({"leisure":"park"}, 2000, None) is None
assert c({"leisure":"garden"}, 2500, "Q1") == ("nature","parc")
assert c({"tourism":"museum"}, 0, None) == ("patrimoine","monument")
assert c({"place":"square"}, 1900, None) == ("patrimoine","monument")
assert c({"place":"square"}, 100, None) is None
assert c({"tourism":"artwork","artwork_type":"statue"}, 0, None) is None
assert c({"tourism":"artwork","artwork_type":"statue"}, 0, "Q1") == ("curiosite","curiosite")
assert c({"historic":"memorial","memorial":"plaque"}, 0, "Q1") is None
assert c({"shop":"supermarket","tourism":"attraction"}, 0, "Q1") is None
assert c({"building":"apartments","heritage":"2"}, 0, "Q1") is None
assert c({"building":"theatre","heritage":"2"}, 0, None) == ("patrimoine","monument")
assert c({"leisure":"playground"}, 12000, "Q1") is None
print("Selection tests OK: mountains, culture, urban nature, exclusions")
