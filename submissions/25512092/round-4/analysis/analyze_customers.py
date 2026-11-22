#!/usr/bin/env python3
"""Tables for analysis/customers.md: the persona sample (analysis/data/personas_sample.jsonl, from sample_personas.py)
against the market's catalog (analysis/data/live_catalog.json, GET https://market.ourolabs.ai/api/catalog).

    python analysis/analyze_customers.py          prints markdown tables (standard library only)

Text fields counted are the ones the market's customer prompt uses (agent-market house/customer.py describe()):
persona, family_persona, culinary_persona, hobbies_and_interests, professional_persona, cultural_background.
Keywords are counted once per persona (document frequency), after a crude Korean particle strip.
"""
import collections
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
PROMPT_TEXT = ("persona", "family_persona", "culinary_persona", "hobbies_and_interests", "professional_persona",
               "cultural_background")

# leaf category (as in /api/demand) -> words a persona would use for it. Hand-made; each word is matched as a substring
# of the persona's prompt text, so words that hide inside other words (김 in 김치, 차 in 자동차) are left out.
CATEGORY_WORDS = {
    "식품>김치/반찬/즉석요리>김치": ["김치", "김장", "깍두기", "겉절이"],
    "식품>김치/반찬/즉석요리>반찬/젓갈": ["반찬", "젓갈", "나물", "장아찌", "밑반찬"],
    "식품>김치/반찬/즉석요리>즉석조리식품": ["간편식", "밀키트", "즉석", "레토르트", "도시락", "편의점", "데워"],
    "식품>김치/반찬/즉석요리>찌개/탕류/장류": ["찌개", "된장", "청국장", "고추장", "국밥", "국물", "곰탕", "탕을"],
    "식품>야채/과일>신선과일(부패주의)": ["과일", "사과", "딸기", "포도", "수박", "제철"],
    "식품>야채/과일>신선야채(부패주의)": ["채소", "야채", "상추", "텃밭", "쌈"],
    "식품>시리얼/곡물/콩류>곡물": ["쌀", "잡곡", "현미", "콩"],
    "식품>계란/유제품>우유/두유": ["우유", "두유", "라떼"],
    "식품>계란/유제품>계란": ["계란", "달걀"],
    "식품>음료>커피/차": ["커피", "원두", "녹차", "보리차", "믹스커피", "카페", "차 한 잔", "차를"],
    "식품>음료>주스/코코아/생수": ["주스", "생수", "음료"],
    "식품>기타 가공식품>과자": ["과자", "간식", "스낵"],
    "식품>기타 가공식품>한과/떡": ["떡", "한과", "약과"],
    "식품>기타 가공식품>국수/파스타/누들": ["국수", "라면", "파스타", "칼국수", "냉면", "우동", "면 요리"],
    "식품>빵/제과>빵": ["빵", "베이커리", "제빵"],
    "식품>육류>신선육류": ["고기", "삼겹살", "소고기", "돼지", "닭", "바비큐", "구이"],
    "식품>육류>가공/조리 육류": ["햄", "소시지", "스팸", "육포", "족발"],
    "식품>해산물>신선생선": ["생선", "고등어", "갈치", "회를", "횟집", "해산물"],
    "식품>해산물>가공/조리 해조류": ["미역", "다시마", "김밥", "조미김"],
    "식품>조리/가공 과일/야채/견과류>조리/가공 견과류": ["견과", "호두", "땅콩", "아몬드"],
    "식품>양념/조미료/소스>소스/양념/조미료": ["양념", "소스", "간장", "참기름", "조미료"],
    "건강용품/식품>다이어트/건강기능>비타민/미네랄/영양제": ["영양제", "비타민", "홍삼", "건강식품", "보양"],
    "가구/침구>침구/홈데코>침구": ["이불", "침구", "베개"],
    "가구/침구>침구/홈데코>커튼/러그/쿠션/덮개": ["인테리어", "커튼", "쿠션"],
    "주방용품>주방용품>주방용품 기타": ["주방", "그릇", "냄비", "프라이팬"],
    "원예/조경>원예/조경>화초": ["화초", "화분", "식물", "꽃", "정원", "원예"],
    "애완용품>애완 케어용품>애완 액세서리": ["반려견", "강아지", "고양이", "반려동물", "반려묘"],
    "스포츠/레저>스포츠/레저>헬스/휘트니스": ["헬스", "운동", "요가", "필라테스", "등산", "골프"],
}

SUFFIX = sorted(["에서는", "으로는", "에서도", "에게서", "이라는", "에서", "으로", "에게", "까지", "부터", "처럼", "보다",
                 "이나", "이며", "이고", "하고", "하며", "하는", "하게", "해서", "하던", "하기", "하여", "했던", "합니다",
                 "입니다", "을", "를", "이", "가", "은", "는", "에", "의", "와", "과", "도", "로", "만", "나", "들", "랑"],
                key=len, reverse=True)
STOP = set("""있는 있습니다 있으며 있어 있고 즐깁니다 즐기는 즐기며 좋아하며 좋아합니다 좋아하는 편이며 편입니다 주말 주말이면
주말에는 평소 자주 함께 직접 가족 시간 가끔 때로는 때 위해 위한 통해 대한 대해 그는 그녀는 자신 자신의 자신만의 사람 사람들
모습 마음 생각 동네 근처 집에서 집 일상 하루 저녁 아침 점심 매일 항상 다양한 새로운 좋은 소소한 특히 주로 또한 그리고 하지만
모든 많은 여유 즐거움 즐겨 즐겨하며 중요하게 중요시 선호하며 선호합니다 관심 관심이 관심을 것을 것이 것은 것 등 및 더 잘 한
번 곳 곳을 수 중 후 전 같은 정도 가장 오랜 오래 즐거운 특별한 소중 소중한 맛 맛을 맛있는 즐깁 이야기 이웃 친구 친구들 동료
동료들 아내 남편 자녀 아이 아이들 부모 부모님 어머니 아버지 손주 씨는 씨의 씨 일주일 음식 식사 가족들 주에 달에 앱으 나오
번은 때는 해결 천천히 최신 긴장 주말에 저녁에 피로 스트레스 거실 풍경 땀을 몸을 오후 퇴근 기분 정성 손맛 메뉴 가격 주변 시장
근처의 한두 두세 서너 일요일 토요일 휴일 쉬는 쉬는날 날에는 날이면 때면 밤에는 이따금 꾸준 꾸준히 넉넉 혼자서 혼자 직장 회사
점심은 저녁은 아침은 끼니 한끼 반주 위주 위주로 즐김 습관 마무리 주방 집밥 사먹 해먹 먹는 시켜 주문해 배달시켜 평소에 이상
후에 따라 잔을 곁들 작은 걷거 누워 정리 변화 인근 평일 계절 전국 분위기 입맛 정식 정갈 경기 시청 영상""".split())
# a stem that still ends like a verb or an adjective is not a keyword (먹으며, 정갈한, 보냅니다, 찾아)
VERBISH = ("며", "다", "고", "서", "게", "던", "요", "지", "면", "니", "으", "어", "아", "여", "데", "한", "된", "운", "적",
           "히", "록", "듯", "죠", "할", "인", "울", "낸", "간", "온", "본", "든", "킨", "르", "려")


def load():
    rows = [json.loads(x) for x in (DATA / "personas_sample.jsonl").open(encoding="utf-8")]
    seen, out = set(), []
    for r in rows:                                     # windows never overlap, but be safe
        if r["uuid"] not in seen:
            seen.add(r["uuid"])
            out.append(r)
    return out


def text(r, fields=PROMPT_TEXT):
    return " ".join(str(r.get(k) or "") for k in fields)


def stems(s):
    out = set()
    for w in re.findall(r"[가-힣]{2,}", s):
        for suf in SUFFIX:
            if w.endswith(suf) and len(w) - len(suf) >= 2:
                w = w[: -len(suf)]
                break
        if len(w) >= 2 and w not in STOP and not w.endswith(VERBISH):
            out.add(w)
    return out


def table(head, rows):
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "-"


def dist(rows, key, top=None):
    c = collections.Counter(key(r) for r in rows)
    items = c.most_common(top)
    return table(["값", "수", "비율"], [(k, v, pct(v, len(rows))) for k, v in items])


def age_band(a):
    a = int(a)
    return "19-29" if a < 30 else "80+" if a >= 80 else f"{a // 10 * 10}대"


GROUPS = {
    "1인 가구": lambda r: str(r["family_type"]).startswith("혼자 거주"),
    "고령 (65+)": lambda r: int(r["age"]) >= 65,
    "자녀 있는 가구": lambda r: "자녀" in str(r["family_type"]) and "손자녀" not in str(r["family_type"]),
    "부부만": lambda r: r["family_type"] == "배우자와 거주",
    "청년 (19-34)": lambda r: int(r["age"]) < 35,
}


def main():
    rows = load()
    n = len(rows)
    print(f"# sample: {n} personas\n")
    print("## fields (sample value lengths)\n")
    print(table(["필드", "평균 길이", "예시 (앞 40자)"],
                [(k, round(sum(len(str(r.get(k) or "")) for r in rows) / n), str(rows[0].get(k))[:40].replace("|", "/"))
                 for k in rows[0]]))
    print("\n## age band\n")
    order = ["19-29", "30대", "40대", "50대", "60대", "70대", "80+"]
    c = collections.Counter(age_band(r["age"]) for r in rows)
    print(table(["연령대", "수", "비율"], [(k, c[k], pct(c[k], n)) for k in order]))
    print(f"\n65+: {pct(sum(int(r['age']) >= 65 for r in rows), n)}, median age {sorted(int(r['age']) for r in rows)[n // 2]}")
    for k, top in (("sex", None), ("province", None), ("occupation", 20), ("family_type", 12), ("housing_type", None),
                   ("marital_status", None)):
        print(f"\n## {k}\n")
        print(dist(rows, lambda r, k=k: r[k], top))
    for f in ("culinary_persona", "hobbies_and_interests"):
        df = collections.Counter()
        for r in rows:
            df.update(stems(str(r.get(f) or "")))
        print(f"\n## top 30 keywords in {f} (personas mentioning)\n")
        print(table(["#", "키워드", "비율"], [(i + 1, w, pct(v, n)) for i, (w, v) in enumerate(df.most_common(30))]))
    demand = {d["category"]: d for d in json.load((DATA / "live_demand.json").open(encoding="utf-8"))}
    texts = [text(r) for r in rows]
    hit = {cat: [any(w in t for w in ws) for t in texts] for cat, ws in CATEGORY_WORDS.items()}
    print("\n## category affinity (share of personas whose prompt text names the category's words)\n")
    ranked = sorted(hit, key=lambda c: -sum(hit[c]))
    print(table(["카테고리", "언급 비율", "SKU 수", "중간 정가", "유통기한 h"],
                [(c, pct(sum(hit[c]), n), demand.get(c, {}).get("skus", "-"), demand.get(c, {}).get("median_price", "-"),
                  demand.get(c, {}).get("shelf_hours") or "공산품") for c in ranked]))
    print("\n## groups: size and the categories they name most above the average (lift)\n")
    out = []
    for g, f in GROUPS.items():
        idx = [i for i, r in enumerate(rows) if f(r)]
        lifts = []
        for c in CATEGORY_WORDS:
            base = sum(hit[c]) / n
            share = sum(hit[c][i] for i in idx) / len(idx) if idx else 0
            if base > 0.02:
                lifts.append((share / base, c, share))
        lifts.sort(reverse=True)
        top = ", ".join(f"{c.split('>')[-1]} {100 * s:.0f}% (x{l:.2f})" for l, c, s in lifts[:5])
        ages = sorted(int(rows[i]["age"]) for i in idx)
        out.append((g, pct(len(idx), n), ages[len(ages) // 2] if ages else "-", top))
    print(table(["손님군", "비율", "중간 나이", "평균보다 많이 언급하는 카테고리 (언급률, 배수)"], out))


if __name__ == "__main__":
    main()
