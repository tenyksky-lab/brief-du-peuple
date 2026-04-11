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

USER_AGENT = "BriefDuPeupleBot/2.0"
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
            if title and link:
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

        if title and link:
            items.append(Entry(title, link, summary, pub, source_name, category))

    return items


def fetch_all_entries(config: dict) -> list[Entry]:
    entries: list[Entry] = []

    for feed in config["feeds"]:
        try:
            data = fetch_url(feed["url"])
            parsed = parse_feed(data, feed["name"], feed["category"])
            entries.extend(parsed)
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
        "impôt", "impots", "impôts", "france", "europe", "economie", "économie"
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


def infer_impact(entry: Entry) -> str:
    text = f"{entry.title} {entry.summary}".lower()

    if any(w in text for w in ["taux", "credit", "crédit", "loan"]):
        return "→ impact possible sur les crédits et le coût de l'argent."
    if any(w in text for w in ["pétrole", "petrole", "oil", "carburant", "énergie", "energie"]):
        return "→ impact possible sur le plein, le transport ou les factures."
    if any(w in text for w in ["emploi", "job", "salaire", "salary", "travail"]):
        return "→ impact possible sur le travail ou le pouvoir d'achat."
    if any(w in text for w in ["inflation", "prix", "price"]):
        return "→ impact possible sur les dépenses du quotidien."
    if any(w in text for w in ["guerre", "attaque", "iran", "ukraine", "frappe"]):
        return "→ à surveiller pour l'énergie, les marchés et les prix."
    if any(w in text for w in ["impôt", "impots", "impôts", "fiscal"]):
        return "→ impact possible sur les impôts, l'épargne ou les obligations déclaratives."
    return "→ à surveiller pour comprendre ce que ça change vraiment."


def build_le_vrai(entries: list[Entry]) -> str:
    blocks = []

    for i, entry in enumerate(entries, start=1):
        title = escape(entry.title)
        desc = escape(infer_impact(entry))
        link = escape(entry.link)

        blocks.append(f"""
<div class="item">
  <span class="item-num">{i:02d}</span>
  <div class="item-body">
    <p class="item-title"><a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a></p>
    <p class="item-text">{desc}</p>
  </div>
</div>
""")

    return "\n".join(blocks)


def make_sous_surface(entries: list[Entry]) -> tuple[str, str]:
    if not entries:
        return (
            "Comprendre l’info au lieu de subir le bruit",
            "Le plus important n’est pas seulement le titre. Ce qui compte, c’est le délai entre l’annonce et l’impact réel sur la vie quotidienne."
        )

    e = entries[0]
    title = clean_text(e.title)
    text = (
        f"Le sujet du jour part de : {title}. Derrière le titre, il faut regarder les effets concrets, "
        "ce qui est confirmé, et ce qui relève encore du bruit. Le bon réflexe est de traduire l’info en impact réel."
    )
    return title, text


def make_action(entries: list[Entry]) -> tuple[str, str]:
    text_blob = " ".join((e.title + " " + e.summary).lower() for e in entries)

    if "carburant" in text_blob or "oil" in text_blob or "pétrole" in text_blob or "petrole" in text_blob:
        return (
            "Surveille tes dépenses transport",
            "Si une baisse est annoncée, évite de payer dans la précipitation. Compare les prix autour de toi avant un gros plein."
        )

    if "taux" in text_blob or "credit" in text_blob or "crédit" in text_blob:
        return (
            "Ne signe pas trop vite un financement",
            "Quand les taux restent hauts, comparer plusieurs offres peut faire économiser de l’argent."
        )

    if "impôt" in text_blob or "impots" in text_blob or "impôts" in text_blob:
        return (
            "Prépare tes papiers avant le dernier moment",
            "Une vérification simple de tes documents et comptes peut éviter des erreurs ou des oublis coûteux."
        )

    return (
        "Action du jour",
        "Prends une info qui te touche vraiment et traduis-la en une seule question : est-ce que ça touche mon budget, mon travail ou mon quotidien ?"
    )


def make_monde(entries: list[Entry]) -> list[str]:
    picked = [
        f"{clean_text(e.title)} {infer_impact(e)}"
        for e in entries
        if e.category == "international"
    ][:3]

    defaults = [
        "Une décision loin de chez toi peut finir par toucher ton budget.",
        "L’international compte surtout quand on le traduit en impact concret.",
        "Le bruit géopolitique finit souvent par se voir sur les prix."
    ]

    while len(picked) < 3:
        picked.append(defaults[len(picked)])

    return picked[:3]


def make_bourse(entries: list[Entry]) -> list[str]:
    text_blob = " ".join((e.title + " " + e.summary).lower() for e in entries)

    l1 = "À surveiller selon l’ambiance économique du jour."
    l2 = "Utile pour sentir la température des marchés tech."
    l3 = "À suivre sans en faire une vérité absolue."
    l4 = "S’il monte, le carburant reste à surveiller."
    l5 = "Impact réel : l’énergie et les taux finissent souvent par toucher le quotidien."

    if "pétrole" in text_blob or "petrole" in text_blob or "oil" in text_blob:
        l4 = "Le pétrole reste un point clé pour le carburant."
        l5 = "Impact réel : si l’énergie monte, ton plein et certaines dépenses peuvent suivre."

    if "taux" in text_blob or "credit" in text_blob or "crédit" in text_blob:
        l5 = "Impact réel : les taux et l’énergie sont deux choses à surveiller de près."

    return [l1, l2, l3, l4, l5]


def make_souverainete() -> dict[str, str]:
    return {
        "titre": "Congés : évite de perdre des jours",
        "intro": "Déjà évoqué — toujours utile aujourd’hui",
        "ligne1": "Certaines entreprises comptent du lundi au samedi",
        "impact": "Ce que ça change :<br>- perte de jours possible<br>- compteur impacté",
        "action": "Ce que tu peux faire :<br>- vérifier ton contrat<br>- adapter tes jours",
        "note": "À vérifier selon ton entreprise"
    }


def make_peuple_topics(entries: list[Entry]) -> list[str]:
    text = " ".join((e.title + " " + e.summary).lower() for e in entries)

    topics = []

    if "inflation" in text or "prix" in text:
        topics.append("Inflation")
    if "carburant" in text or "pétrole" in text or "petrole" in text:
        topics.append("Carburant")
    if "impôt" in text or "impôts" in text or "impots" in text:
        topics.append("Impôts")
    if "banque" in text or "crédit" in text or "credit" in text:
        topics.append("Banque / Crédit")
    if "travail" in text or "emploi" in text:
        topics.append("Travail / Salaire")

    defaults = ["Inflation", "Carburant", "Impôts"]
    for item in defaults:
        if item not in topics:
            topics.append(item)

    return topics[:3]


def make_question_du_peuple(now: datetime) -> str:
    if now.day <= 7:
        return "Ce mois-ci, qu’est-ce qui vous impacte le plus ? Répondez simplement à ce mail : carburant, courses, banque, logement ou travail."
    return "Vous bossez dans quoi ? Répondez directement à ce mail."


def make_punchline() -> str:
    return "Ce que tu ne comprends pas te contrôle."


def replace_all(template: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def main() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE))
    config = load_config()
    entries = dedupe(fetch_all_entries(config))
    top = pick_top(entries, 3)

    sous_titre, sous_texte = make_sous_surface(top)
    action_titre, action_texte = make_action(top)
    monde = make_monde(entries)
    bourse = make_bourse(entries)
    souverainete = make_souverainete()
    topics = make_peuple_topics(entries)

    mapping = {
        "DATE_LONG": escape(now.strftime("%d/%m/%Y")),
        "LE_VRAI_ITEMS": build_le_vrai(top),
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
        "SOUV_INTRO": souverainete["intro"],
        "SOUV_LIGNE1": souverainete["ligne1"],
        "SOUV_IMPACT": souverainete["impact"],
        "SOUV_ACTION": souverainete["action"],
        "SOUV_NOTE": escape(souverainete["note"]),
        "TOPIC_1": escape(topics[0]),
        "TOPIC_2": escape(topics[1]),
        "TOPIC_3": escape(topics[2]),
        "QUESTION_DU_PEUPLE": escape(make_question_du_peuple(now)),
        "PUNCHLINE": escape(make_punchline()),
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    output = replace_all(template, mapping)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print("Brief généré avec vraies news.")


if __name__ == "__main__":
    main()
