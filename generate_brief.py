from __future__ import annotations

import json
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "sources.json"
TEMPLATE_PATH = ROOT / "index.template.html"
OUTPUT_PATH = ROOT / "index.html"

USER_AGENT = "BriefDuPeupleBot/4.0"
MAX_FETCH_PER_FEED = 8
TIMEZONE = "Europe/Paris"


@dataclass
class Entry:
    title: str
    link: str
    summary: str
    published: datetime | None
    source: str
    category: str


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return resp.read()


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_datetime(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text)
    except Exception:
        return None


def parse_feed(xml_bytes: bytes, source_name: str, category: str) -> list[Entry]:
    items: list[Entry] = []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    rss_items = root.findall(".//channel/item")
    if rss_items:
        for item in rss_items[:MAX_FETCH_PER_FEED]:
            title = clean_text(item.findtext("title", ""))
            link = clean_text(item.findtext("link", ""))
            summary = clean_text(item.findtext("description", "")) or title
            pub = parse_datetime(item.findtext("pubDate"))
            if title:
                items.append(Entry(title, link, summary, pub, source_name, category))
        return items

    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for entry in atom_entries[:MAX_FETCH_PER_FEED]:
        title = clean_text(entry.findtext("{http://www.w3.org/2005/Atom}title", ""))
        summary = clean_text(
            entry.findtext("{http://www.w3.org/2005/Atom}summary", "")
            or entry.findtext("{http://www.w3.org/2005/Atom}content", "")
            or title
        )

        link = ""
        for link_el in entry.findall("{http://www.w3.org/2005/Atom}link"):
            href = link_el.attrib.get("href")
            if href:
                link = href
                break

        pub = parse_datetime(
            entry.findtext("{http://www.w3.org/2005/Atom}updated")
            or entry.findtext("{http://www.w3.org/2005/Atom}published")
        )

        if title:
            items.append(Entry(title, link, summary, pub, source_name, category))

    return items


def fetch_all_entries(config: dict) -> list[Entry]:
    entries: list[Entry] = []

    for feed in config["feeds"]:
        try:
            data = fetch_url(feed["url"])
            entries.extend(parse_feed(data, feed["name"], feed["category"]))
        except Exception as exc:
            print(f"Erreur flux {feed['name']}: {exc}")

    return entries


def dedupe(entries: list[Entry]) -> list[Entry]:
    seen = set()
    out: list[Entry] = []

    for e in entries:
        key = re.sub(r"\W+", "", e.title.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(e)

    return out


def score_entry(entry: Entry) -> int:
    score = 0
    text = f"{entry.title} {entry.summary}".lower()

    priority_words = [
        "prix", "inflation", "taux", "énergie", "energie", "emploi", "travail",
        "budget", "salaire", "logement", "carburant", "pétrole", "petrole",
        "banque", "crédit", "credit", "bourse", "iran", "guerre", "attaque",
        "impôt", "impots", "impôts", "france", "europe", "economie", "économie",
        "jardin", "chauffage", "électricité", "electricite", "courses"
    ]

    for word in priority_words:
        if word in text:
            score += 2

    if entry.category in {"economie", "societe"}:
        score += 2

    if entry.published:
        score += 1

    return score


def pick_top(entries: list[Entry], count: int) -> list[Entry]:
    return sorted(
        entries,
        key=lambda e: (score_entry(e), e.published or datetime.min),
        reverse=True
    )[:count]


def normalize_title(title: str) -> str:
    t = clean_text(title)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace(" : ", " : ")
    return t[:140].rstrip(" .")


def make_human_title(entry: Entry) -> str:
    title = normalize_title(entry.title)
    lower = title.lower()

    if "carburant" in lower or "pétrole" in lower or "petrole" in lower:
        return title
    if "impôt" in lower or "impots" in lower or "impôts" in lower:
        return title
    if "taux" in lower or "crédit" in lower or "credit" in lower:
        return title
    if "guerre" in lower or "iran" in lower or "attaque" in lower:
        return title

    return title


def infer_impact(entry: Entry) -> str:
    text = f"{entry.title} {entry.summary}".lower()

    if any(w in text for w in ["taux", "credit", "crédit", "loan"]):
        return "→ à surveiller si tu comptes emprunter, renégocier un crédit ou financer un projet."
    if any(w in text for w in ["pétrole", "petrole", "oil", "carburant", "énergie", "energie"]):
        return "→ ton plein, certains transports et une partie de tes dépenses peuvent encore bouger."
    if any(w in text for w in ["emploi", "job", "salaire", "salary", "travail"]):
        return "→ ça peut peser sur le travail, les salaires ou le pouvoir d’achat."
    if any(w in text for w in ["inflation", "prix", "price", "courses"]):
        return "→ ça peut se voir rapidement sur les courses, les factures ou le budget du mois."
    if any(w in text for w in ["guerre", "attaque", "iran", "ukraine", "frappe"]):
        return "→ à surveiller de près pour l’énergie, les marchés et le coût de la vie."
    if any(w in text for w in ["impôt", "impots", "impôts", "fiscal", "déclaration"]):
        return "→ mieux vaut vérifier tôt pour éviter les oublis, les erreurs ou les mauvaises surprises."
    if any(w in text for w in ["banque"]):
        return "→ ça peut toucher l’épargne, les frais ou l’accès au crédit."
    return "→ l’important n’est pas le bruit, mais ce que ça peut changer concrètement pour toi."


def build_essentiel(entries: list[Entry]) -> dict[str, str]:
    default_titles = [
        "Les prix restent le vrai sujet du moment",
        "Les annonces économiques continuent de peser",
        "Le quotidien reste sous pression sur plusieurs fronts",
    ]
    default_impacts = [
        "→ courses, énergie ou transport : ce sont souvent les mêmes dépenses qui prennent en premier.",
        "→ ce qui compte n’est pas l’annonce, mais son effet réel sur ton budget.",
        "→ mieux vaut regarder l’impact concret que le titre brut."
    ]

    out = {}
    for idx in range(3):
        if idx < len(entries):
            out[f"TITRE_{idx+1}"] = make_human_title(entries[idx])
            out[f"IMPACT_{idx+1}"] = infer_impact(entries[idx])
        else:
            out[f"TITRE_{idx+1}"] = default_titles[idx]
            out[f"IMPACT_{idx+1}"] = default_impacts[idx]
    return out


def make_sous_surface(entries: list[Entry]) -> tuple[str, str]:
    if not entries:
        return (
            "Ce qu’on raconte n’est pas toujours ce qui compte vraiment",
            "Le vrai sujet n’est pas seulement le titre. Ce qui compte, c’est le moment où tu ressens l’impact sur ton budget, ton travail ou ton quotidien."
        )

    e = entries[0]
    title = make_human_title(e)
    text = (
        f"On parle beaucoup de : {title}. Mais le plus important n’est pas seulement l’annonce. "
        "Il faut regarder ce qui est confirmé, ce qui relève encore du bruit, et surtout quand l’effet réel se voit dans la vie quotidienne. "
        "Le bon réflexe n’est pas de paniquer : c’est de traduire l’info en conséquence concrète."
    )
    return title, text


def make_action(entries: list[Entry]) -> tuple[str, str]:
    text_blob = " ".join((e.title + " " + e.summary).lower() for e in entries)

    if "carburant" in text_blob or "oil" in text_blob or "pétrole" in text_blob or "petrole" in text_blob:
        return (
            "Avant ton prochain plein, compare vraiment",
            "Avant de faire un gros plein ce week-end, regarde au moins deux stations autour de toi. Quelques centimes d’écart suffisent à faire une vraie différence à la fin du mois."
        )

    if "taux" in text_blob or "credit" in text_blob or "crédit" in text_blob:
        return (
            "Ne signe rien dans la précipitation",
            "Si tu dois financer un achat, prends le temps de comparer plusieurs offres. Même un petit écart sur un taux peut coûter cher sur la durée."
        )

    if "impôt" in text_blob or "impots" in text_blob or "impôts" in text_blob or "déclaration" in text_blob:
        return (
            "Prépare tes papiers avant le dernier moment",
            "Une simple vérification de tes documents, comptes ou justificatifs peut éviter des erreurs coûteuses au moment de déclarer."
        )

    if "emploi" in text_blob or "travail" in text_blob or "salaire" in text_blob:
        return (
            "Regarde ce qui te touche vraiment",
            "Avant de passer à autre chose, pose-toi une seule question : est-ce que cette info change quelque chose pour mon travail, mon budget ou ma famille ?"
        )

    return (
        "Cherche l’impact réel, pas le bruit",
        "Lis moins de titres et pose-toi une meilleure question : qu’est-ce que ça change vraiment pour moi cette semaine ?"
    )


def make_monde(entries: list[Entry]) -> list[str]:
    picked = [
        f"{make_human_title(e)} {infer_impact(e)}"
        for e in entries
        if e.category == "international"
    ][:3]

    defaults = [
        "Ce qui se passe loin de chez toi finit souvent par toucher l’énergie, les marchés ou les prix.",
        "L’international n’a d’intérêt que s’il est traduit en impact concret.",
        "Le bruit géopolitique n’est utile que si on comprend ce qu’il change réellement."
    ]

    while len(picked) < 3:
        picked.append(defaults[len(picked)])

    return picked[:3]


def make_bourse(entries: list[Entry]) -> list[str]:
    text_blob = " ".join((e.title + " " + e.summary).lower() for e in entries)

    l1 = "repère global à surveiller selon l’ambiance économique du jour"
    l2 = "utile pour sentir la température des marchés tech"
    l3 = "à suivre sans en faire une vérité absolue"
    l4 = "le pétrole reste un point clé pour le carburant"
    l5 = "Impact réel : les taux et l’énergie restent les deux choses à surveiller de près."

    if "pétrole" in text_blob or "petrole" in text_blob or "oil" in text_blob:
        l4 = "si le pétrole remonte, ton plein peut suivre avec retard"
        l5 = "Impact réel : si l’énergie repart, le carburant et plusieurs dépenses peuvent remonter."
    if "taux" in text_blob or "credit" in text_blob or "crédit" in text_blob:
        l5 = "Impact réel : les taux élevés continuent de peser sur le crédit, l’immobilier et le budget."

    return [l1, l2, l3, l4, l5]


def make_souverainete(now: datetime) -> dict[str, str]:
    month = now.month

    if month in [4, 5, 6]:
        return {
            "titre": "Déclaration : mieux vaut vérifier tôt",
            "texte": "Période fiscale oblige, beaucoup attendent le dernier moment. Vérifie maintenant tes documents, tes comptes à l’étranger si tu en as, et les éléments qui peuvent changer ton imposition. Les oublis coûtent souvent plus cher que le temps pris pour relire.",
            "note": "À vérifier selon ta situation."
        }

    return {
        "titre": "Congés : évite de perdre des jours",
        "texte": "Dans certaines entreprises, les congés sont comptés du lundi au samedi. Résultat : poser jeudi et vendredi peut parfois faire tomber un jour en plus. Vérifie si tes congés sont comptés en jours ouvrés ou ouvrables avant de poser tes dates.",
        "note": "À vérifier selon ton entreprise."
    }


def make_saison(now: datetime) -> tuple[str, str]:
    month = now.month

    if month in [3, 4, 5]:
        return (
            "Printemps : le bon moment pour remettre dehors, planter et entretenir",
            "Beaucoup commencent à jardiner ou à remettre les extérieurs en état. C’est le bon moment pour semis simples, nettoyage léger, taille d’entretien et premiers achats utiles. Si tu compares un peu, certaines enseignes sortent aussi des promos sur le terreau, les outils ou les plants."
        )

    if month in [6, 7, 8]:
        return (
            "Été : attention à l’eau, au jardin et aux dépenses qui grimpent vite",
            "En été, l’arrosage, le carburant et les sorties font vite monter la note. Arrose tôt ou tard, évite les achats dans l’urgence et regarde les promos utiles avant les gros déplacements ou les travaux extérieurs."
        )

    if month in [9, 10, 11]:
        return (
            "Automne : préparer maintenant évite de payer plus cher ensuite",
            "C’est le moment de nettoyer, protéger et anticiper l’hiver. Gouttières, chauffage, petit entretien extérieur : ce qui est fait maintenant évite souvent des réparations ou des achats plus chers ensuite."
        )

    return (
        "Hiver : chauffage, énergie et maison deviennent prioritaires",
        "Quand il fait froid, le vrai sujet redevient la consommation : chauffage, humidité, isolation, petits gestes utiles. Une amélioration simple et bien faite vaut souvent mieux qu’une grosse dépense improvisée."
    )


def make_peuple_topics(entries: list[Entry], now: datetime) -> list[str]:
    text = " ".join((e.title + " " + e.summary).lower() for e in entries)
    topics = []

    if "inflation" in text or "prix" in text or "courses" in text:
        topics.append("Prix du quotidien")
    if "carburant" in text or "pétrole" in text or "petrole" in text:
        topics.append("Carburant / énergie")
    if "impôt" in text or "impôts" in text or "impots" in text:
        topics.append("Impôts / déclaration")
    if "banque" in text or "crédit" in text or "credit" in text:
        topics.append("Banque / crédit")
    if "travail" in text or "emploi" in text or "salaire" in text:
        topics.append("Travail / salaire")

    month = now.month
    if month in [3, 4, 5]:
        topics.append("Jardin / extérieur")
    elif month in [6, 7, 8]:
        topics.append("Vacances / carburant")
    elif month in [9, 10, 11]:
        topics.append("Maison / entretien")
    else:
        topics.append("Chauffage / factures")

    cleaned = []
    for topic in topics:
        if topic not in cleaned:
            cleaned.append(topic)

    defaults = ["Prix du quotidien", "Carburant / énergie", "Impôts / déclaration"]
    for topic in defaults:
        if topic not in cleaned:
            cleaned.append(topic)

    return cleaned[:3]


def make_question_du_peuple(now: datetime) -> str:
    if now.day <= 7:
        return "Ce mois-ci, qu’est-ce qui vous pèse le plus ? Répondez simplement à ce mail : carburant, courses, banque, logement, travail ou autre."
    return "Vous bossez dans quoi ? Répondez directement à ce mail."


def make_punchline(entries: list[Entry], now: datetime) -> str:
    month = now.month
    text_blob = " ".join((e.title + " " + e.summary).lower() for e in entries)

    seasonal = {
        "spring": [
            "Ce que tu prépares maintenant t’évitera de payer plus cher plus tard.",
            "Le bon moment passe vite. Les bonnes décisions aussi.",
        ],
        "summer": [
            "En été, ce qui coûte le plus n’est pas toujours ce qu’on voit d’abord.",
            "Quand tout augmente doucement, on finit par payer fort.",
        ],
        "autumn": [
            "Ce que tu anticipes aujourd’hui te protège cet hiver.",
            "Ce qu’on repousse en automne coûte souvent plus cher en hiver.",
        ],
        "winter": [
            "Quand l’énergie grimpe, l’erreur la plus chère est d’attendre.",
            "L’hiver rappelle toujours la même chose : mieux vaut prévoir que subir.",
        ],
    }

    if "carburant" in text_blob or "pétrole" in text_blob or "petrole" in text_blob:
        return "Ce que tu ne regardes pas à la pompe finit souvent par se voir sur tout le reste."

    if "impôt" in text_blob or "impôts" in text_blob or "impots" in text_blob:
        return "Ce que tu oublies sur le papier peut coûter bien plus cher en vrai."

    if "taux" in text_blob or "credit" in text_blob or "crédit" in text_blob:
        return "Quand l’argent coûte cher, chaque décision pèse plus longtemps."

    if month in [3, 4, 5]:
        return seasonal["spring"][0]
    if month in [6, 7, 8]:
        return seasonal["summer"][0]
    if month in [9, 10, 11]:
        return seasonal["autumn"][0]
    return seasonal["winter"][0]


def replace_all(template: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def main() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE))
    config = load_config()
    entries = dedupe(fetch_all_entries(config))
    top = pick_top(entries, 3)

    essentiel = build_essentiel(top)
    sous_titre, sous_texte = make_sous_surface(top)
    action_titre, action_texte = make_action(top)
    monde = make_monde(entries)
    bourse = make_bourse(entries)
    souverainete = make_souverainete(now)
    saison_titre, saison_texte = make_saison(now)
    topics = make_peuple_topics(entries, now)
    question = make_question_du_peuple(now)
    punchline = make_punchline(entries, now)

    mapping = {
        "DATE_LONG": escape(now.strftime("%d/%m/%Y")),

        "TITRE_1": escape(essentiel["TITRE_1"]),
        "IMPACT_1": escape(essentiel["IMPACT_1"]),
        "TITRE_2": escape(essentiel["TITRE_2"]),
        "IMPACT_2": escape(essentiel["IMPACT_2"]),
        "TITRE_3": escape(essentiel["TITRE_3"]),
        "IMPACT_3": escape(essentiel["IMPACT_3"]),

        "SOUS_SURFACE_TITRE": escape(sous_titre),
        "SOUS_SURFACE_TEXTE": escape(sous_texte),

        "ACTION_TITRE": escape(action_titre),
        "ACTION_TEXTE": escape(action_texte),

        "MONDE_1": escape(monde[0]),
        "MONDE_2": escape(monde[1]),
        "MONDE_3": escape(monde[2]),

        "BOURSE_1": escape(bourse[0]),
        "BOURSE_2": escape(bourse[1]),
        "BOURSE_3": escape(bourse[2]),
        "BOURSE_4": escape(bourse[3]),
        "BOURSE_5": escape(bourse[4]),

        "SOUV_TITRE": escape(souverainete["titre"]),
        "SOUV_TEXTE": escape(souverainete["texte"]),
        "SOUV_NOTE": escape(souverainete["note"]),

        "SAISON_TITRE": escape(saison_titre),
        "SAISON_TEXTE": escape(saison_texte),

        "TOPIC_1": escape(topics[0]),
        "TOPIC_2": escape(topics[1]),
        "TOPIC_3": escape(topics[2]),

        "QUESTION_DU_PEUPLE": escape(question),
        "PUNCHLINE": escape(punchline),
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    output = replace_all(template, mapping)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print("Brief généré V4.")
    

if __name__ == "__main__":
    main()
