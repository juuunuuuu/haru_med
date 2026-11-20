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


def get_recent_pmids(query: str, retmax: int = 35) -> list[str]:
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
    당신은 인스타그램 '@haru_med' 계정을 운영하는 의학 에디터입니다.
    의대생과 의료인은 물론, 의학에 관심 있는 독자들도 흥미롭게 읽을 수 있도록 **연구 논문과 에세이 사이의 따뜻하고 명쾌한 어조**로 하루 2개의 게시물(각 5장 분량)을 작성해 주세요.

    [1. 논문 2편 선별 기준]
    - 아래 {len(candidates)}개의 후보 중 **서로 다른 의학 분야이면서 임상적·학술적 비중이 가장 큰 연구 2편**을 고르세요.
    - 대규모 코호트/임상시험(RCT), 기존의 의학적 통념을 검증하거나 뒤집는 연구, 주요 질환의 새로운 치료 패러다임을 제시하는 연구를 최우선으로 선택하세요.

    [2. 문체 및 작성 원칙 - 매우 중요]
    - **딱딱한 논문 요약투 금지:** "본 연구는 ~를 평가하고자 하였다", "통계적으로 유의한 차이를 보였다(p<0.001)" 같은 건조한 번역투를 절대 쓰지 마세요.
    - **이야기하듯 풀어쓰기:** 실제 임상 현장의 궁금증이나 맥락에서 수필처럼 자연스럽게 이야기를 시작하세요.
    - **기전과 핵심 개념은 정확하게:** 쉬운 말로 풀어쓰되, 핵심 의학 개념(병태생리, 수용체, 약리 기전 등)은 정확한 용어와 영어 원어를 괄호로 병기해 깊이를 유지하세요. (예: 뇌혈관장벽(BBB), 다면발현 효과(pleiotropic effects))
    - **가독성:** 각 슬라이드 본문은 3~4문장 이내로 호흡을 짧게 끊고, 문단 사이는 `<br><br>`로 나누세요. 핵심 구절은 `<b>강조할 내용</b>` 태그로 감싸세요 (슬라이드당 1~2곳).

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
              "body": "임상 현장에서 마주하는 궁금증이나 기존 치료의 한계, 오랫동안 이어진 의학적 논란을 수필처럼 자연스럽게 소개 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "02 · 몸속에서 일어나는 일",
              "heading": "핵심 기전과 원리 소제목",
              "body": "이 연구를 이해하기 위해 꼭 알아야 할 병태생리나 약물 작용 기전(MOA)을 비유와 정확한 의학 용어(영어 병기)를 섞어 알기 쉽게 해설 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "03 · 연구가 밝혀낸 사실",
              "heading": "연구 결과를 담은 소제목",
              "body": "어떤 사람들을 얼마나 추적했는지, 그리고 실제로 어떤 결과가 나왔는지를 복잡한 통계 용어 없이 명쾌하게 전달 (3~4문장, <br><br>로 문단 구분)"
            }},
            {{
              "step": "04 · 기억해 둘 임상 포인트",
              "heading": "진료실 적용과 핵심 용어 정리",
              "body": "이 결과가 실제 진료와 환자 설명에 어떤 의미를 주는지 정리하고, 함께 기억해 둘 핵심 의학 개념 1가지를 짚어주며 마무리 (3~4문장, <br><br>로 문단 구분)"
            }}
          ],
          "caption": "인스타그램 게시물 본문 (따뜻한 도입부 + 오늘의 연구 요약 + 본문에 나온 핵심 의학 용어 2가지 간단 해설 + 출처(저널명, 논문 원제, PMID) + 해시태그 12개: #하루의학 #의대생 #의학공부 #임상의학 #의학논문 #저널클럽 #건강의학 #전공의 #의학지식 #북스타그램 등)"
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
        background: #F8FAFC; color: #1E293B;
        display: flex; flex-direction: column; justify-content: space-between;
        padding: 84px 80px;
        word-break: keep-all;
      }
      .top-bar {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 26px; font-weight: 700; color: #0F766E;
      }
      .badge {
        background: #CCFBF1; color: #0F766E;
        padding: 12px 26px; border-radius: 999px; font-size: 25px;
      }
      .footer {
        display: flex; justify-content: space-between; align-items: center;
        border-top: 2px solid #E2E8F0; padding-top: 32px;
        font-size: 24px; color: #64748B; font-weight: 600;
      }
      b { color: #0F766E; background: #F0FDFA; padding: 3px 9px; border-radius: 6px; font-weight: 700; }
    </style>
    """

    if is_cover:
        return f"""
        <html><head><meta charset="UTF-8">{base_css}
        <style>
          body {{ background: linear-gradient(155deg, #134E4A 0%, #0F172A 100%); color: #FFFFFF; }}
          .badge {{ background: rgba(45, 212, 191, 0.18); color: #5EEAD4; border: 1px solid rgba(94, 234, 212, 0.35); }}
          .top-bar {{ color: #99F6E4; }}
          .cover-main {{ margin: auto 0; }}
          .eyebrow {{ font-size: 26px; font-weight: 600; color: #5EEAD4; margin-bottom: 24px; }}
          .cover-title {{ font-size: 68px; font-weight: 800; line-height: 1.32; margin-bottom: 36px; letter-spacing: -0.02em; }}
          .cover-sub {{ font-size: 35px; line-height: 1.6; color: #E2E8F0; font-weight: 400; }}
          .footer {{ border-top-color: rgba(255,255,255,0.16); color: #CBD5E1; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span class="badge">{data['category']}</span>
            <span>하루 한 편, 의학 브리핑</span>
          </div>
          <div class="cover-main">
            <div class="eyebrow">TODAY'S CLINICAL STORY</div>
            <div class="cover-title">{data['cover_title']}</div>
            <div class="cover-sub">{data['cover_subtitle']}</div>
          </div>
          <div class="footer">
            <span>{data['journal']}</span>
            <span>@haru_med · 밀어서 읽기 →</span>
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
          .step-label {{ font-size: 26px; font-weight: 800; color: #0F766E; margin-bottom: 18px; }}
          .heading {{ font-size: 46px; font-weight: 800; line-height: 1.34; margin-bottom: 40px; color: #0F172A; letter-spacing: -0.01em; }}
          .body-text {{ font-size: 35px; line-height: 1.72; color: #334155; }}
        </style></head>
        <body>
          <div class="top-bar">
            <span>하루 한 편, 의학 브리핑</span>
            <span>{page_num} / 5</span>
          </div>
          <div class="content-box">
            <div class="step-label">{slide['step']}</div>
            <div class="heading">{slide['heading']}</div>
            <div class="body-text">{slide['body']}</div>
          </div>
          <div class="footer">
            <span>{data['journal']} · PMID {data['pmid']}</span>
            <span>@haru_med</span>
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

    recent_pmids = get_recent_pmids(PUBMED_QUERY, retmax=35)
    unseen_pmids = [p for p in recent_pmids if p not in history][:15]
    candidates = fetch_candidates_details(unseen_pmids)

    if len(candidates) < 2:
        print("새로운 후보 논문이 충분하지 않습니다.")
        return

    paired_posts = create_two_card_scripts(candidates)
    today_str = datetime.now().strftime("%Y-%m-%d")
    saved_posts = []

    for post_num, (chosen, script) in enumerate(paired_posts, start=1):
        script["post_num"] = post_num
        script["journal"] = chosen["journal"]
        script["pmid"] = chosen["pmid"]
        script["date"] = today_str

        cover_html = build_slide_html(is_cover=True, data=script)
        render_html_to_png(cover_html, f"{OUTPUT_DIR}/post{post_num}_slide_1.png")

        for idx, slide in enumerate(script["slides"], start=2):
            slide_html = build_slide_html(is_cover=False, data=script, slide=slide, page_num=idx)
            render_html_to_png(slide_html, f"{OUTPUT_DIR}/post{post_num}_slide_{idx}.png")

        history.append(chosen["pmid"])
        saved_posts.append(script)
        print(f"[{post_num}번째 카드뉴스 생성 완료] {script['cover_title']}")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today_str, "posts": saved_posts}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
