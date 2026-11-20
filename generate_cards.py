import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

# 의대생·의료인 필독 주요 임상/의과학 저널 필터
PUBMED_QUERY = (
    '("New England Journal of Medicine"[Journal] OR "Lancet"[Journal] OR '
    '"JAMA"[Journal] OR "Nature medicine"[Journal] OR "BMJ"[Journal] OR '
    '"Annals of internal medicine"[Journal] OR "Neurology"[Journal] OR "Circulation"[Journal]) '
    'AND hasabstract[text] '
    'NOT ("Letter"[pt] OR "Editorial"[pt] OR "Comment"[pt] OR "Published Erratum"[pt])'
)
OUTPUT_DIR = "output"
HISTORY_FILE = "output/history.json"
LATEST_FILE = "output/latest.json"


def get_recent_pmids(query: str, retmax: int = 25) -> list[str]:
    encoded_query = urllib.parse.quote(query)
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        f"db=pubmed&term={encoded_query}&retmax={retmax}&sort=pub+date&retmode=json"
    )
    with urllib.request.urlopen(url) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])


def fetch_candidates_details(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    ids_str = ",".join(pmids)
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={ids_str}&retmode=xml"
    with urllib.request.urlopen(url) as res:
        xml_data = res.read()

    root = ET.fromstring(xml_data)
    candidates = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID", default="").strip()
        title_elem = article.find(".//ArticleTitle")
        title = "".join(title_elem.itertext()).strip() if title_elem is not None else ""
        journal = article.findtext(".//Journal/Title", default="Unknown Journal")

        abstract_parts = []
        for elem in article.findall(".//Abstract/AbstractText"):
            label = elem.attrib.get("Label", "")
            text = "".join(elem.itertext()).strip()
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(abstract_parts)

        if pmid and len(abstract) > 300:
            candidates.append({
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "abstract": abstract,
            })
    return candidates


def create_card_script(candidates: list
