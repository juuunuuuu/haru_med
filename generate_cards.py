import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

PUBMED_QUERY = (
    '("New England Journal of Medicine"[Journal] OR "Lancet"[Journal] OR '
    '"JAMA"[Journal] OR "Nature medicine"[Journal] OR "BMJ"[Journal] OR '
    '"Neurology"[Journal] OR "Circulation"[Journal]) '
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


def create_card_script(candidates: list[dict]) -> tuple[dict, dict]:
    client = genai.Client()
    candidates_text = ""
    for idx, c in enumerate(candidates):
        candidates_text += f"\n--- [후보 {idx}] ---\n저널: {c['journal']}\n제목: {c['title']}\n초록:\n{c['abstract']}\n"

    prompt = f"""
    당신은 최신 의학 연구와 핵심 의학 개념을 알기 쉽게 풀어주는 인스타그램 의학 카드뉴스 에디터입니다.
    아래 후보 논문 중 **사람들이 흥미로워할 만한 임상 연구 1편**을 골라 총 5장의 카드뉴스 슬라이드 대본과 인스타 본문(캡션)을 작성해 주세요.

    [작성 규칙]
    1. 모바일 화면에서 한눈에 읽히도록 문장은 짧고 명확하게 작성하세요.
    2. 딱딱한 통계 용어(p값, 신뢰구간 등)는 빼고, **질환의 기본 개념과 작용 기전(원리)**을 직관적으로 설명하세요.
    3. 강조하고 싶은 핵심 키워드는 `<b>강조단어</b>` 태그로 감싸주세요 (슬라이드당 1~2곳).

    [후보 논문 목록]
    {candidates_text}

    반드시 아래 JSON 형식으로만 응답하세요:
    {{
      "selected_index": 선택한 후보 번호 (0 ~ {len(candidates) - 1}),
      "category": "분과 태그 (예: #신경학 #편두통)",
      "cover_title": "표지 메인 타이틀 (호기심을 끄는 2줄 이내 헤드라인, 줄바꿈은 <br> 사용)",
      "cover_subtitle": "표지 부제목 (1줄 요약)",
      "slides": [
        {{
          "step": "01 · 배경 개념",
          "heading": "이 질환/상황, 왜 생길까?",
          "body": "논문을 이해하기 위한 기본 질환 개념과 기존 치료의 한계 (3~4문장, 가독성 좋게 <br><br>로 문단 구분)"
        }},
        {{
          "step": "02 · 핵심 원리",
          "heading": "이번 연구의 핵심 타겟",
          "body": "논문에 등장하는 핵심 의학 개념·물질·기전(예: CGRP, 수용체, 병태생리 등)을 알기 쉽게 설명 (3~4문장, <br><br>로 문단 구분)"
        }},
        {{
          "step": "03 · 연구 결과",
          "heading": "실제로 어떤 효과가 있었을까?",
          "body": "연구 대상과 핵심 임상 결과를 쉬운 말로 정리 (3~4문장, <br><br>로 문단 구분)"
        }},
        {{
          "step": "04 · 오늘의 요약",
          "heading": "한눈에 보는 핵심 정리",
          "body": "임상적 의의와 기억해 둘 핵심 포인트 2~3가지 (3~4문장, <br><br>로 문단 구분)"
        }}
      ],
      "caption": "인스타그램 게시물 본문 (흥미를 끄는 첫 줄 + 연구 요약 + 관련 의학 개념 복습 + 출처 저널명 표기 + 하단 관련 해시태그 10개 포함)"
    }}
    """

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )
    result = json.loads(response.text)
    idx = result.pop("selected_index", 0)
    if not (0 <= idx < len(candidates)):
        idx = 0
    return candidates[idx], result


def render_html_to_png(html_content: str, output_path: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
        page.set_content(html_content, wait_until="networkidle")
        page.screenshot(path=output_path)
        browser.close()


def build_slide_html(is_cover: bool, data: dict, slide: dict = None, page_num: int = 1) -> str:
    base_css = """
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body {
        width: 1080px; height: 1350px;
        font-family: 'Noto Sans CJK KR', 'Noto Sans KR', sans-serif;
        background: #F8FAFC; color: #0F172A;
        display: flex; flex-direction: column; justify-content: space-between;
        padding: 84px 80px;
        word-break: keep-all;
      }
      .top-bar {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 28px; font-weight: 700; color: #0F766E;
      }
      .badge {
        background: #CCFBF1; color: #0F766E;
        padding: 12px 26px; border-radius: 999px; font-size: 26px;
      }
      .footer {
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid #E2E8F0; padding-top: 32px;
        font-size: 24px; color: #64748B; font-weight: 600;
      }
      b { color: #0F766E; background: #F0FDFA; padding: 2px 8px; border-radius: 6px; }
    </style>
    """

    if is_cover:
        return f"""
        <html><head><meta charset="UTF-8">{base_css}
        <style>
          body {{ background: linear-gradient(145deg, #0F766E 0%, #115E59 100%); color: #FFFFFF; }}
          .badge {{ background: rgba(255,255,255,0.18); color: #FFFFFF; }}
          .top-bar {{ color: #CCFBF1; }}
          .cover-main {{ my-auto; }}
          .cover-title {{ font-size: 74px; font-weight: 800; line-height: 1.28; margin-bottom: 36px; letter-spacing: -0.02em; }}
          .cover-sub {{ font-size: 36px; line-height: 1.55; color: #E2E8F0; font-weight: 400; }}
          .footer {{ border-top-color: rgba(255,255,255,0.2); color: #CCFBF1; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span class="badge">{data['category']}</span>
            <span>DAILY MED BRIEF</span>
          </div>
          <div class="cover-main">
            <div class="cover-title">{data['cover_title']}</div>
            <div class="cover-sub">{data['cover_subtitle']}</div>
          </div>
          <div class="footer">
            <span>출처: {data['journal']}</span>
            <span>밀어서 개념 보기 →</span>
          </div>
        </body></html>
        """
    else:
        return f"""
        <html><head><meta charset="UTF-8">{base_css}
        <style>
          .content-box {{
            background: #FFFFFF; border-radius: 36px; padding: 68px 60px;
            box-shadow: 0 12px 36px rgba(15, 23, 42, 0.06);
            border: 2px solid #E2E8F0;
            flex-grow: 1; margin: 44px 0;
            display: flex; flex-direction: column; justify-content: center;
          }}
          .step-label {{ font-size: 28px; font-weight: 800; color: #0F766E; margin-bottom: 20px; }}
          .heading {{ font-size: 50px; font-weight: 800; line-height: 1.3; margin-bottom: 44px; color: #0F172A; }}
          .body-text {{ font-size: 36px; line-height: 1.68; color: #334155; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span>DAILY MED BRIEF</span>
            <span>{page_num} / 5</span>
          </div>
          <div class="content-box">
            <div class="step-label">{slide['step']}</div>
            <div class="heading">{slide['heading']}</div>
            <div class="body-text">{slide['body']}</div>
          </div>
          <div class="footer">
            <span>{data['journal']}</span>
            <span>@daily_med_brief</span>
          </div>
        </body></html>
        """


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = []

    recent_pmids = get_recent_pmids(PUBMED_QUERY, retmax=25)
    unseen_pmids = [p for p in recent_pmids if p not in history][:10]
    candidates = fetch_candidates_details(unseen_pmids)

    if not candidates:
        print("새로운 후보 논문이 없습니다.")
        return

    chosen, script = create_card_script(candidates)
    script["journal"] = chosen["journal"]
    script["pmid"] = chosen["pmid"]
    script["date"] = datetime.now().strftime("%Y-%m-%d")

    # 1번 표지 렌더링
    cover_html = build_slide_html(is_cover=True, data=script)
    render_html_to_png(cover_html, f"{OUTPUT_DIR}/slide_1.png")

    # 2~5번 본문 카드 렌더링
    for idx, slide in enumerate(script["slides"], start=2):
        slide_html = build_slide_html(is_cover=False, data=script, slide=slide, page_num=idx)
        render_html_to_png(slide_html, f"{OUTPUT_DIR}/slide_{idx}.png")

    history.append(chosen["pmid"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"카드뉴스 5장 생성 완료: {script['cover_title']}")


if __name__ == "__main__":
    main()
