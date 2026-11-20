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


def create_card_script(candidates: list[dict]) -> tuple[dict, dict]:
    client = genai.Client()
    candidates_text = ""
    for idx, c in enumerate(candidates):
        candidates_text += f"\n--- [후보 {idx}] ---\n저널: {c['journal']}\n제목: {c['title']}\n초록:\n{c['abstract']}\n"

    prompt = f"""
    당신은 의대생과 젊은 임상의들을 위해 최신 임상 연구와 핵심 의학 개념을 명쾌하게 정리해 주는 '1분 저널클럽' 인스타그램 에디터입니다.
    아래 후보 논문 중 **임상적 파급력과 학습 가치가 가장 높은 연구 1편**을 골라 총 5장의 카드뉴스 슬라이드 대본과 인스타 본문(캡션)을 작성해 주세요.

    [작성 원칙 - 의대생·의료인 타겟]
    1. **정확한 의학 용어 사용:** 핵심 질환명, 수용체, 병태생리, 약물 기전 용어는 한국어와 영어 원어를 병기하세요. (예: 칼시토닌 유전자 관련 펩타이드(CGRP), 특발성 두개내압 상승증(IIH))
    2. **연구 기법·통계 나열 지양:** 복잡한 p값, 신뢰구간(95% CI), 다변량 보정 모델 설명은 빼고, **임상적 기전과 환자 치료의 변화**에 집중하세요.
    3. **카드뉴스 가독성:** 한 슬라이드당 3~4문장 이내로 간결하게 끊어 쓰고, 문단 사이는 `<br><br>`로 구분하세요. 강조할 핵심 개념은 `<b>강조단어</b>` 태그로 감싸세요 (슬라이드당 1~2곳).

    [후보 논문 목록]
    {candidates_text}

    반드시 아래 JSON 형식으로만 응답하세요:
    {{
      "selected_index": 선택한 후보 번호 (0 ~ {len(candidates) - 1}),
      "category": "분과 및 핵심 키워드 (예: 신경학 · 편두통)",
      "cover_title": "표지 메인 타이틀 (임상적 핵심이 드러나는 2줄 이내 헤드라인, 줄바꿈은 <br> 사용)",
      "cover_subtitle": "표지 부제목 (연구의 핵심 의의를 1줄로 요약)",
      "slides": [
        {{
          "step": "01 · CLINICAL CONTEXT",
          "heading": "질환 배경 및 기존 치료의 한계",
          "body": "해당 질환의 핵심 병태생리와 기존 표준 치료(Standard of Care)가 가진 임상적 한계점을 설명 (3~4문장, <br><br>로 문단 구분)"
        }},
        {{
          "step": "02 · MECHANISM & TARGET",
          "heading": "핵심 기전 및 작용 원리",
          "body": "이 연구의 핵심 타겟(수용체, 바이오마커, 병리 기전)과 치료제/중재의 작용 원리(MOA)를 의학적으로 명쾌하게 해설 (3~4문장, <br><br>로 문단 구분)"
        }},
        {{
          "step": "03 · KEY OUTCOMES",
          "heading": "주요 임상 결과",
          "body": "대상 환자군과 중재 내용, 그리고 임상적으로 의미 있는 핵심 유효성 및 안전성(이상반응) 결과를 깔끔하게 정리 (3~4문장, <br><br>로 문단 구분)"
        }},
        {{
          "step": "04 · CLINICAL PEARL",
          "heading": "진료실 적용 & 핵심 용어 복습",
          "body": "실제 임상 현장에서 어떤 환자에게 고려할 수 있는지(Clinical Pearl)와 함께 기억해 둘 핵심 의학 개념 1~2가지를 정리 (3~4문장, <br><br>로 문단 구분)"
        }}
      ],
      "caption": "인스타그램 게시물 본문 (핵심 요약 3줄 + 주요 의학 개념 정리 + 원문 출처(저널명, 논문 원제, PMID) + 의대생·의료인 타겟 해시태그 12개 포함: #의대생 #본과 #의학공부 #의학논문 #저널클럽 #임상의학 #전공의 등)"
    }}
    """

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.35,
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
        font-size: 26px; font-weight: 700; letter-spacing: 0.04em; color: #0F766E;
      }
      .badge {
        background: #CCFBF1; color: #0F766E;
        padding: 12px 26px; border-radius: 999px; font-size: 25px; letter-spacing: 0;
      }
      .footer {
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid #E2E8F0; padding-top: 32px;
        font-size: 24px; color: #64748B; font-weight: 600;
      }
      b { color: #0F766E; background: #F0FDFA; padding: 2px 8px; border-radius: 6px; font-weight: 700; }
    </style>
    """

    if is_cover:
        return f"""
        <html><head><meta charset="UTF-8">{base_css}
        <style>
          body {{ background: linear-gradient(150deg, #0F172A 0%, #1E293B 100%); color: #FFFFFF; }}
          .badge {{ background: rgba(45, 212, 191, 0.16); color: #2DD4BF; border: 1px solid rgba(45, 212, 191, 0.35); }}
          .top-bar {{ color: #94A3B8; }}
          .cover-main {{ margin: auto 0; }}
          .eyebrow {{ font-size: 26px; font-weight: 700; color: #2DD4BF; letter-spacing: 0.08em; margin-bottom: 24px; }}
          .cover-title {{ font-size: 70px; font-weight: 800; line-height: 1.28; margin-bottom: 36px; letter-spacing: -0.02em; }}
          .cover-sub {{ font-size: 35px; line-height: 1.55; color: #CBD5E1; font-weight: 400; }}
          .footer {{ border-top-color: rgba(255,255,255,0.15); color: #94A3B8; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span class="badge">{data['category']}</span>
            <span>MED JOURNAL CLUB</span>
          </div>
          <div class="cover-main">
            <div class="eyebrow">TODAY'S CLINICAL BRIEF</div>
            <div class="cover-title">{data['cover_title']}</div>
            <div class="cover-sub">{data['cover_subtitle']}</div>
          </div>
          <div class="footer">
            <span>{data['journal']}</span>
            <span>밀어서 기전·임상 요약 보기 →</span>
          </div>
        </body></html>
        """
    else:
        return f"""
        <html><head><meta charset="UTF-8">{base_css}
        <style>
          .content-box {{
            background: #FFFFFF; border-radius: 32px; padding: 64px 58px;
            box-shadow: 0 12px 36px rgba(15, 23, 42, 0.05);
            border: 2px solid #E2E8F0;
            border-top: 10px solid #0F766E;
            flex-grow: 1; margin: 44px 0;
            display: flex; flex-direction: column; justify-content: center;
          }}
          .step-label {{ font-size: 25px; font-weight: 800; color: #0F766E; letter-spacing: 0.06em; margin-bottom: 18px; }}
          .heading {{ font-size: 48px; font-weight: 800; line-height: 1.3; margin-bottom: 42px; color: #0F172A; letter-spacing: -0.01em; }}
          .body-text {{ font-size: 35px; line-height: 1.68; color: #334155; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span>MED JOURNAL CLUB</span>
            <span>0{page_num} / 05</span>
          </div>
          <div class="content-box">
            <div class="step-label">{slide['step']}</div>
            <div class="heading">{slide['heading']}</div>
            <div class="body-text">{slide['body']}</div>
          </div>
          <div class="footer">
            <span>{data['journal']} · PMID {data['pmid']}</span>
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

    cover_html = build_slide_html(is_cover=True, data=script)
    render_html_to_png(cover_html, f"{OUTPUT_DIR}/slide_1.png")

    for idx, slide in enumerate(script["slides"], start=2):
        slide_html = build_slide_html(is_cover=False, data=script, slide=slide, page_num=idx)
        render_html_to_png(slide_html, f"{OUTPUT_DIR}/slide_{idx}.png")

    history.append(chosen["pmid"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"의대생·의료인 타겟 카드뉴스 5장 생성 완료: {script['cover_title']}")


if __name__ == "__main__":
    main()
