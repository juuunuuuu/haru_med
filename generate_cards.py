import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

# 의학 전반의 최상위 임상·의과학 저널 필터
PUBMED_QUERY = (
    '("New England Journal of Medicine"[Journal] OR "Lancet"[Journal] OR '
    '"JAMA"[Journal] OR "Nature medicine"[Journal] OR "BMJ"[Journal] OR '
    '"Annals of internal medicine"[Journal] OR "Circulation"[Journal] OR '
    '"Neurology"[Journal] OR "Gastroenterology"[Journal] OR "JAMA internal medicine"[Journal]) '
    'AND hasabstract[text] '
    'NOT ("Letter"[pt] OR "Editorial"[pt] OR "Comment"[pt] OR "Published Erratum"[pt])'
)
OUTPUT_DIR = "output"
HISTORY_FILE = "output/history.json"
LATEST_FILE = "output/latest.json"

# GPU 없이도 0.1초 만에 렌더링되는 가벼운 미세 종이 직조(Linen/Paper) 텍스쳐
SHARED_TEXTURE_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    width: 1080px; height: 1350px;
    font-family: 'Noto Sans CJK KR', 'Noto Sans KR', sans-serif;
    position: relative;
    overflow: hidden;
    display: flex; flex-direction: column; justify-content: space-between;
    padding: 84px 80px;
    word-break: keep-all;
  }
  .paper-weave {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 50;
    background-image:
      repeating-linear-gradient(0deg, rgba(15, 23, 42, 0.018) 0px, rgba(15, 23, 42, 0.018) 1px, transparent 1px, transparent 4px),
      repeating-linear-gradient(90deg, rgba(15, 23, 42, 0.015) 0px, rgba(15, 23, 42, 0.015) 1px, transparent 1px, transparent 4px);
  }
"""

# 게시물별 순환 적용할 3가지 컬러 & 텍스쳐 테마
POST_THEMES = [
    {
        "name": "Forest Teal",
        "cover_bg_color": "#134E4A",
        "cover_gradient": (
            "radial-gradient(circle at 86% 16%, rgba(253, 230, 138, 0.24) 0%, rgba(253, 230, 138, 0) 44%), "
            "radial-gradient(circle at 12% 88%, rgba(45, 212, 191, 0.22) 0%, rgba(15, 23, 42, 0.65) 75%), "
            "linear-gradient(155deg, #134E4A 0%, #0D3B38 55%, #0F172A 100%)"
        ),
        "cover_top_color": "#A7F3D0",
        "cover_badge_bg": "rgba(253, 230, 138, 0.16)",
        "cover_badge_color": "#FDE68A",
        "cover_badge_border": "rgba(253, 230, 138, 0.4)",
        "cover_eyebrow_color": "#5EEAD4",
        "cover_dot_color": "#FDE68A",
        "page_bg": "#F4F7F5",
        "dot_rgba": "rgba(15, 118, 110, 0.09)",
        "glow_rgba": "rgba(204, 251, 241, 0.55)",
        "primary": "#0F766E",
        "primary_dark": "#134E4A",
        "pill_bg": "#E6F4F1",
        "bold_color": "#0F766E",
        "bold_bg": "#E6F4F1",
        "card_border": "rgba(19, 78, 74, 0.12)",
        "card_shadow": "rgba(19, 78, 74, 0.06)",
        "concept_accents": ["#0F766E", "#115E59", "#0D9488"],
    },
    {
        "name": "Morning Amber",
        "cover_bg_color": "#78350F",
        "cover_gradient": (
            "radial-gradient(circle at 85% 18%, rgba(254, 240, 138, 0.30) 0%, rgba(254, 240, 138, 0) 46%), "
            "radial-gradient(circle at 15% 88%, rgba(217, 119, 6, 0.28) 0%, rgba(28, 25, 23, 0.72) 75%), "
            "linear-gradient(155deg, #78350F 0%, #5C280B 52%, #1C1917 100%)"
        ),
        "cover_top_color": "#FDE68A",
        "cover_badge_bg": "rgba(254, 243, 199, 0.16)",
        "cover_badge_color": "#FEF3C7",
        "cover_badge_border": "rgba(254, 243, 199, 0.4)",
        "cover_eyebrow_color": "#FCD34D",
        "cover_dot_color": "#FEF08A",
        "page_bg": "#FAF7F2",
        "dot_rgba": "rgba(180, 83, 9, 0.08)",
        "glow_rgba": "rgba(254, 243, 199, 0.65)",
        "primary": "#B45309",
        "primary_dark": "#78350F",
        "pill_bg": "#FEF3C7",
        "bold_color": "#92400E",
        "bold_bg": "#FEF3C7",
        "card_border": "rgba(120, 53, 15, 0.12)",
        "card_shadow": "rgba(120, 53, 15, 0.06)",
        "concept_accents": ["#B45309", "#D97706", "#92400E"],
    },
    {
        "name": "Midnight Slate",
        "cover_bg_color": "#1E293B",
        "cover_gradient": (
            "radial-gradient(circle at 86% 16%, rgba(186, 230, 253, 0.22) 0%, rgba(186, 230, 253, 0) 44%), "
            "radial-gradient(circle at 12% 88%, rgba(56, 189, 248, 0.18) 0%, rgba(15, 23, 42, 0.75) 75%), "
            "linear-gradient(155deg, #1E3A5F 0%, #1E293B 55%, #0F172A 100%)"
        ),
        "cover_top_color": "#BAE6FD",
        "cover_badge_bg": "rgba(186, 230, 253, 0.16)",
        "cover_badge_color": "#E0F2FE",
        "cover_badge_border": "rgba(186, 230, 253, 0.38)",
        "cover_eyebrow_color": "#7DD3FC",
        "cover_dot_color": "#BAE6FD",
        "page_bg": "#F4F6F9",
        "dot_rgba": "rgba(30, 58, 95, 0.08)",
        "glow_rgba": "rgba(224, 242, 254, 0.6)",
        "primary": "#1E40AF",
        "primary_dark": "#1E293B",
        "pill_bg": "#DBEAFE",
        "bold_color": "#1E3A8A",
        "bold_bg": "#DBEAFE",
        "card_border": "rgba(30, 41, 59, 0.12)",
        "card_shadow": "rgba(30, 41, 59, 0.06)",
        "concept_accents": ["#1E40AF", "#1D4ED8", "#0369A1"],
    },
]


def get_recent_pmids(query: str, retmax: int = 35) -> list[str]:
    encoded_query = urllib.parse.quote(query)
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        f"db=pubmed&term={encoded_query}&retmax={retmax}&sort=pub+date&retmode=json"
    )
    with urllib.request.urlopen(url, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])


def fetch_candidates_details(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    ids_str = ",".join(pmids)
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={ids_str}&retmode=xml"
    with urllib.request.urlopen(url, timeout=30) as res:
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

        if pmid and len(abstract) > 350:
            candidates.append({
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "abstract": abstract,
            })
    return candidates


def create_two_card_scripts(candidates: list[dict]) -> list[tuple[dict, dict]]:
    client = genai.Client()
    candidates_text = ""
    for idx, c in enumerate(candidates):
        candidates_text += f"\n--- [후보 {idx}] ---\n저널: {c['journal']}\n제목: {c['title']}\n초록:\n{c['abstract']}\n"

    prompt = f"""
    당신은 인스타그램 '@haruachim_med' 계정을 운영하는 의학 에디터입니다.
    의대생과 의료인이 환자의 질문에 최신 근거를 더해 답할 수 있도록, **연구 논문과 에세이 사이의 따뜻하고 명쾌한 어조**로 하루 2개의 게시물(각 6장 분량)을 작성해 주세요.

    [1. 논문 2편 선별 기준]
    - 아래 {len(candidates)}개의 후보 중 **서로 다른 의학 분야이면서 임상적·학술적 비중이 가장 큰 연구 2편**을 고르세요.
    - 대규모 코호트/임상시험(RCT), 기존의 의학적 통념을 검증하거나 뒤집는 연구, 주요 질환의 새로운 치료 패러다임을 제시하는 연구를 최우선으로 선택하세요.

    [2. 문체 및 작성 원칙 - 매우 중요]
    - **딱딱한 논문 요약투 금지:** "본 연구는 ~를 평가하고자 하였다", "통계적으로 유의한 차이를 보였다(p<0.001)" 같은 건조한 번역투를 절대 쓰지 마세요.
    - **이야기하듯 풀어쓰기:** 실제 진료실에서 환자가 던지는 질문이나 임상 현장의 궁금증에서 수필처럼 자연스럽게 이야기를 시작하세요.
    - **가독성:** 각 슬라이드 본문은 3~4문장 이내로 호흡을 짧게 끊고, 문단 사이는 `<br><br>`로 나누세요. 핵심 구절은 `<b>강조할 내용</b>` 태그로 감싸세요 (슬라이드당 1~2곳).
    - **6번째 슬라이드(핵심 의학 개념 정리):** 통계·역학·연구방법론 용어는 절대 넣지 말고, 질환의 병태생리·생리학·약물 작용 기전(MOA) 등 **순수 의학 개념 2~3가지(영어 원어 병기)**만 알기 쉽게 정리하세요.

    [후보 논문 목록]
    {candidates_text}

    반드시 아래 JSON 형식으로만 응답하세요 (posts 배열 안에 정확히 2개의 서로 다른 논문 브리핑 포함):
    {{
      "posts": [
        {{
          "selected_index": 선택한 후보 번호 (0 ~ {len(candidates) - 1}),
          "category": "분과 · 핵심 키워드 (예: 순환기내과 · 고지혈증)",
          "cover_title": "표지 메인 타이틀 (호기심을 자극하는 질문형 또는 명쾌한 2줄 헤드라인, 줄바꿈은 <br> 사용)",
          "cover_subtitle": "표지 부제목 (연구가 던지는 핵심 메시지를 부드러운 1줄로 요약)",
          "slides": [
            {{
              "step": "01 · 진료실의 궁금증",
              "heading": "이야기를 여는 소제목 (질문형 또는 맥락 제시)",
              "body": "진료실에서 마주하는 환자의 질문이나 기존 치료의 한계, 오랫동안 이어진 의학적 논란을 수필처럼 자연스럽게 소개 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "02 · 몸속에서 일어나는 일",
              "heading": "핵심 기전과 원리 소제목",
              "body": "이 연구를 이해하기 위해 꼭 알아야 할 병태생리나 약물 작용 기전(MOA)을 비유와 정확한 의학 용어를 섞어 알기 쉽게 해설 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "03 · 연구가 밝혀낸 사실",
              "heading": "연구 결과를 담은 소제목",
              "body": "어떤 사람들을 얼마나 추적했는지, 그리고 실제로 어떤 결과가 나왔는지를 복잡한 통계 용어 없이 명쾌하게 전달 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "04 · 진료실 적용 포인트",
              "heading": "환자에게 이렇게 설명해 보세요",
              "body": "이 결과가 실제 진료와 환자 상담에 어떤 의미를 주는지, 어떤 환자에게 어떻게 적용할 수 있을지 명쾌하게 정리 (3~4문장, <br><br>로 문단 구분)"
            }}
          ],
          "key_concepts": [
            {{
              "term": "핵심 의학 개념 용어 (영어 원어 병기)",
              "explanation": "교과서적인 딱딱한 정의 대신, 임상적 맥락에서 왜 중요한지 쉽게 풀어쓴 설명 (2문장 이내)"
            }}
          ],
          "caption": "인스타그램 게시물 본문 (따뜻한 도입부 + 오늘의 연구 요약 + 관련 의학 개념 복습 + 출처(저널명, 논문 원제, PMID) + 면책문구 + 해시태그 12개: #하루아침_med #의대생 #의학공부 #임상의학 #의학논문 #저널클럽 #건강의학 #전공의 #의학지식 #북스타그램 등)"
        }}
      ]
    }}
    """

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.45,
        ),
    )
    result = json.loads(response.text)
    posts = result.get("posts", [])[:2]

    paired = []
    used_indices = set()
    for post in posts:
        idx = post.pop("selected_index", 0)
        if not (0 <= idx < len(candidates)) or idx in used_indices:
            for fallback_idx in range(len(candidates)):
                if fallback_idx not in used_indices:
                    idx = fallback_idx
                    break
        used_indices.add(idx)
        paired.append((candidates[idx], post))

    return paired


def build_cover_html(data: dict, theme: dict) -> str:
    return f"""
    <html><head><meta charset="UTF-8">
    <style>
      {SHARED_TEXTURE_CSS}
      body {{
        background-color: {theme['cover_bg_color']};
        background-image: {theme['cover_gradient']};
        color: #FFFFFF;
      }}
      .grid-overlay {{
        position: absolute; inset: 0; pointer-events: none;
        background-image: radial-gradient(rgba(255, 255, 255, 0.08) 1.5px, transparent 1.5px);
        background-size: 32px 32px;
      }}
      .top-bar {{
        display: flex; justify-content: space-between; align-items: center;
        font-size: 26px; font-weight: 700; color: {theme['cover_top_color']}; z-index: 2;
      }}
      .badge {{
        background: {theme['cover_badge_bg']}; color: {theme['cover_badge_color']};
        border: 1px solid {theme['cover_badge_border']};
        padding: 12px 26px; border-radius: 999px; font-size: 25px;
      }}
      .cover-main {{ margin: auto 0; z-index: 2; }}
      .eyebrow {{
        display: inline-flex; align-items: center; gap: 10px;
        font-size: 25px; font-weight: 700; color: {theme['cover_eyebrow_color']};
        letter-spacing: 0.06em; margin-bottom: 26px;
      }}
      .sun-dot {{
        width: 14px; height: 14px; border-radius: 50%;
        background: {theme['cover_dot_color']}; display: inline-block;
      }}
      .cover-title {{ font-size: 68px; font-weight: 800; line-height: 1.32; margin-bottom: 36px; letter-spacing: -0.02em; }}
      .cover-sub {{ font-size: 35px; line-height: 1.62; color: #E2E8F0; font-weight: 400; }}
      .footer {{
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid rgba(255,255,255,0.18); padding-top: 32px;
        font-size: 24px; color: #CBD5E1; font-weight: 600; z-index: 2;
      }}
    </style></head>
    <body>
      <div class="paper-weave"></div>
      <div class="grid-overlay"></div>
      <div class="top-bar">
        <span class="badge">{data['category']}</span>
        <span>하루아침_med</span>
      </div>
      <div class="cover-main">
        <div class="eyebrow"><span class="sun-dot"></span> TODAY'S CLINICAL STORY</div>
        <div class="cover-title">{data['cover_title']}</div>
        <div class="cover-sub">{data['cover_subtitle']}</div>
      </div>
      <div class="footer">
        <span>{data['journal']}</span>
        <span>@haruachim_med · 밀어서 읽기 →</span>
      </div>
    </body></html>
    """


def build_body_html(data: dict, slide: dict, page_num: int, theme: dict) -> str:
    return f"""
    <html><head><meta charset="UTF-8">
    <style>
      {SHARED_TEXTURE_CSS}
      body {{
        background-color: {theme['page_bg']};
        background-image:
          radial-gradient(circle at 90% 10%, {theme['glow_rgba']} 0%, transparent 45%),
          radial-gradient({theme['dot_rgba']} 1.5px, transparent 1.5px);
        background-size: 100% 100%, 28px 28px;
        color: #1E293B;
      }}
      .top-bar {{
        display: flex; justify-content: space-between; align-items: center;
        font-size: 26px; font-weight: 700; color: {theme['primary_dark']}; z-index: 2;
      }}
      .page-pill {{
        background: {theme['pill_bg']}; color: {theme['primary']};
        padding: 8px 22px; border-radius: 999px; font-size: 24px; font-weight: 800;
      }}
      .content-box {{
        background: #FFFFFF; border-radius: 32px; padding: 64px 58px;
        box-shadow: 0 14px 36px {theme['card_shadow']};
        border: 2px solid {theme['card_border']};
        border-top: 12px solid {theme['primary']};
        flex-grow: 1; margin: 42px 0;
        display: flex; flex-direction: column; justify-content: center;
        z-index: 2;
      }}
      .step-label {{ font-size: 26px; font-weight: 800; color: {theme['primary']}; margin-bottom: 18px; }}
      .heading {{ font-size: 46px; font-weight: 800; line-height: 1.34; margin-bottom: 40px; color: #0F172A; letter-spacing: -0.01em; }}
      .body-text {{ font-size: 35px; line-height: 1.72; color: #334155; }}
      b {{ color: {theme['bold_color']}; background: {theme['bold_bg']}; padding: 3px 10px; border-radius: 7px; font-weight: 700; }}
      .footer {{
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid {theme['card_border']}; padding-top: 32px;
        font-size: 24px; color: #475569; font-weight: 600; z-index: 2;
      }}
    </style></head>
    <body>
      <div class="paper-weave"></div>
      <div class="top-bar">
        <span>하루아침_med</span>
        <span class="page-pill">{page_num} / 6</span>
      </div>
      <div class="content-box">
        <div class="step-label">{slide['step']}</div>
        <div class="heading">{slide['heading']}</div>
        <div class="body-text">{slide['body']}</div>
      </div>
      <div class="footer">
        <span>{data['journal']} · PMID {data['pmid']}</span>
        <span>@haruachim_med</span>
      </div>
    </body></html>
    """


def build_concepts_html(data: dict, theme: dict) -> str:
    concepts = data.get("key_concepts", [])[:3]
    accents = theme["concept_accents"]
    cards_html = ""
    for idx, c in enumerate(concepts):
        c_color = accents[idx % len(accents)]
        cards_html += f"""
        <div class="concept-card" style="border-left-color: {c_color};">
          <div class="concept-term" style="color: {c_color};">{c['term']}</div>
          <div class="concept-desc">{c['explanation']}</div>
        </div>
        """

    return f"""
    <html><head><meta charset="UTF-8">
    <style>
      {SHARED_TEXTURE_CSS}
      body {{
        background-color: {theme['page_bg']};
        background-image:
          radial-gradient(circle at 90% 10%, {theme['glow_rgba']} 0%, transparent 45%),
          radial-gradient({theme['dot_rgba']} 1.5px, transparent 1.5px);
        background-size: 100% 100%, 28px 28px;
        color: #1E293B;
      }}
      .top-bar {{
        display: flex; justify-content: space-between; align-items: center;
        font-size: 26px; font-weight: 700; color: {theme['primary_dark']}; z-index: 2;
      }}
      .page-pill {{
        background: {theme['pill_bg']}; color: {theme['primary']};
        padding: 8px 22px; border-radius: 999px; font-size: 24px; font-weight: 800;
      }}
      .main-area {{
        flex-grow: 1; margin: 38px 0;
        display: flex; flex-direction: column; justify-content: center;
        z-index: 2;
      }}
      .step-label {{ font-size: 26px; font-weight: 800; color: {theme['primary']}; margin-bottom: 14px; }}
      .heading {{ font-size: 44px; font-weight: 800; line-height: 1.3; margin-bottom: 34px; color: #0F172A; }}
      .concept-card {{
        background: #FFFFFF; border-radius: 24px; padding: 34px 38px;
        border: 2px solid {theme['card_border']}; border-left: 11px solid {theme['primary']};
        margin-bottom: 24px;
        box-shadow: 0 10px 26px {theme['card_shadow']};
      }}
      .concept-card:last-child {{ margin-bottom: 0; }}
      .concept-term {{ font-size: 32px; font-weight: 800; margin-bottom: 12px; }}
      .concept-desc {{ font-size: 29px; line-height: 1.62; color: #334155; }}
      .footer {{
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid {theme['card_border']}; padding-top: 32px;
        font-size: 24px; color: #475569; font-weight: 600; z-index: 2;
      }}
    </style></head>
    <body>
      <div class="paper-weave"></div>
      <div class="top-bar">
        <span>하루아침_med</span>
        <span class="page-pill">6 / 6</span>
      </div>
      <div class="main-area">
        <div class="step-label">05 · KEY MEDICAL CONCEPTS</div>
        <div class="heading">함께 알아둘 핵심 의학 개념</div>
        {cards_html}
      </div>
      <div class="footer">
        <span>저장해 두고 복습하세요 📌</span>
        <span>@haruachim_med</span>
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

    print("1. PubMed 최신 논문 검색 중...")
    recent_pmids = get_recent_pmids(PUBMED_QUERY, retmax=35)
    unseen_pmids = [p for p in recent_pmids if p not in history][:15]
    candidates = fetch_candidates_details(unseen_pmids)

    if len(candidates) < 2:
        print("새로운 후보 논문이 충분하지 않습니다.")
        return

    print("2. Gemini 에디터 대본 작성 중...")
    paired_posts = create_two_card_scripts(candidates)
    today_str = datetime.now().strftime("%Y-%m-%d")
    saved_posts = []

    print("3. 카드뉴스 12장 이미지 렌더링 시작...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1.5)

        for post_num, (chosen, script) in enumerate(paired_posts, start=1):
            theme = POST_THEMES[len(history) % len(POST_THEMES)]

            script["post_num"] = post_num
            script["theme_name"] = theme["name"]
            script["journal"] = chosen["journal"]
            script["pmid"] = chosen["pmid"]
            script["date"] = today_str

            page.set_content(build_cover_html(script, theme), wait_until="domcontentloaded")
            page.screenshot(path=f"{OUTPUT_DIR}/post{post_num}_slide_1.png")

            for idx, slide in enumerate(script["slides"], start=2):
                page.set_content(build_body_html(script, slide, idx, theme), wait_until="domcontentloaded")
                page.screenshot(path=f"{OUTPUT_DIR}/post{post_num}_slide_{idx}.png")

            page.set_content(build_concepts_html(script, theme), wait_until="domcontentloaded")
            page.screenshot(path=f"{OUTPUT_DIR}/post{post_num}_slide_6.png")

            history.append(chosen["pmid"])
            saved_posts.append(script)
            print(f"[{post_num}번째 카드뉴스 6장 완료 - {theme['name']}] {script['cover_title']}")

        browser.close()

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today_str, "posts": saved_posts}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
