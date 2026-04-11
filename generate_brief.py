import json
from datetime import datetime

# Charger template
with open("index.template.html", "r", encoding="utf-8") as f:
    template = f.read()

# Charger sources (juste pour test pour l'instant)
with open("sources.json", "r", encoding="utf-8") as f:
    sources = json.load(f)

# Remplissage simple (version V1 stable)
data = {
    "DATE_LONG": datetime.now().strftime("%d %B %Y"),

    "LE_VRAI_ITEMS": """
<div class="item"><span class="item-num">01</span> Info importante du jour</div>
<div class="item"><span class="item-num">02</span> Deuxième info clé</div>
<div class="item"><span class="item-num">03</span> Troisième info utile</div>
""",

    "SOUS_SURFACE_TITRE": "Ce qu'on ne te dit pas",
    "SOUS_SURFACE_TEXTE": "Analyse simple d’un sujet important.",

    "ACTION_TITRE": "Ce que tu peux faire",
    "ACTION_TEXTE": "Une action concrète aujourd’hui.",

    "MONDE_1": "Info mondiale 1",
    "MONDE_2": "Info mondiale 2",
    "MONDE_3": "Info mondiale 3",

    "BOURSE_1": "+0.5%",
    "BOURSE_2": "-0.2%",
    "BOURSE_3": "+1.2%",
    "BOURSE_4": "+0.8%",
    "BOURSE_5": "Marché stable aujourd’hui.",

    "SOUV_TITRE": "Congés : évite de perdre des jours",
    "SOUV_INTRO": "Déjà évoqué — toujours utile",
    "SOUV_LIGNE1": "Certaines entreprises comptent du lundi au samedi",
    "SOUV_IMPACT": "- perte de jours possible<br>- compteur impacté",
    "SOUV_ACTION": "- vérifier ton contrat<br>- adapter tes jours",
    "SOUV_NOTE": "À vérifier selon ton entreprise",

    "TOPIC_1": "Inflation",
    "TOPIC_2": "Carburant",
    "TOPIC_3": "Impôts",

    "QUESTION_DU_PEUPLE": "Vous bossez dans quoi ?",
    "PUNCHLINE": "Ce que tu ne comprends pas te contrôle."
}

# Remplacement
for key, value in data.items():
    template = template.replace("{{" + key + "}}", value)

# Générer index.html
with open("index.html", "w", encoding="utf-8") as f:
    f.write(template)

print("Brief généré")
