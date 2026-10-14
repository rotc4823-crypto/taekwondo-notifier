import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
HISTORY_FILE = "history.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

KTA_LIST = "https://www.koreataekwondo.co.kr/f001"
WTA_API = "https://wta.kukkiwon.or.kr/api/recruit/getRecruitList"
WTA_PAGE = "https://wta.kukkiwon.or.kr/kr/recruit/list?menuid=80&topMenuid=79"

KTA_WORDS = ("연수", "강습", "교육", "아카데미", "양성")


def fetch(url, data=None, headers=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def kta_items():
    """대한태권도협회 공지: 제목에 '심판'과 연수/강습/교육 계열 단어가 있는 글"""
    page = fetch(KTA_LIST)
    items = []
    for m in re.finditer(r'<a[^>]+href="(https://www\.koreataekwondo\.co\.kr/f001/post/(\d+))"[^>]*>(.*?)</a>', page, re.S):
        url, pid, inner = m.groups()
        title = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        title = re.sub(r"\s+", " ", title).strip()
        if not title or "심판" not in title:
            continue
        if not any(w in title for w in KTA_WORDS):
            continue
        items.append({"id": "kta-" + pid, "src": "대한태권도협회", "title": title, "url": url, "extra": ""})
    seen, out = set(), []
    for i in items:
        if i["id"] not in seen:
            seen.add(i["id"])
            out.append(i)
    return out


def wta_items():
    """국기원 세계태권도연수원 모집공고: 제목에 '심사위원' 또는 승품/승단 심사 관련 글"""
    body = json.dumps({"page": 1, "offset": 0, "limit": 100,
                       "data": {"languageType": "$KR", "cosWay": "", "applyOnly": False}}).encode()
    res = json.loads(fetch(WTA_API, body, {"Content-Type": "application/json"}))
    out = []
    for o in res.get("data") or []:
        title = (o.get("title") or "").replace(";;", " / ")
        if "심사위원" not in title and "승품" not in title and "승단" not in title:
            continue
        rng = o.get("recruitDateRange") or {}
        extra = ""
        if rng.get("startDate"):
            extra = f"접수기간: {rng['startDate']} ~ {rng.get('endDate')}"
        out.append({"id": "wta-%s" % o.get("id"), "src": "국기원 세계태권도연수원",
                    "title": f"{title} ({o.get('cosWayName', '')})", "url": WTA_PAGE, "extra": extra})
    return out


def kgta_items():
    """경기도태권도협회 RSS(공지사항 게시판 /39/): 고단자 또는 6단 심사 안내 글만"""
    xml = fetch("https://kgta.org/rss")
    entries = re.findall(r"<item>(.*?)</item>", xml, re.S)
    print("KGTA RSS 항목", len(entries))
    out = []
    for it in entries:
        tm = re.search(r"<title>(.*?)</title>", it, re.S)
        lm = re.search(r"<link>(.*?)</link>", it, re.S)
        if not tm or not lm:
            continue
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", tm.group(1))).strip()
        link = html.unescape(lm.group(1)).strip()
        m = re.search(r"kgta\.org/39/\?idx=(\d+)", link)
        if not m:
            continue
        if "고단자" not in title and not re.search(r"6\s*단|6\s*-\s*9\s*단", title):
            continue
        out.append({"id": "kgta-" + m.group(1), "src": "경기도태권도협회", "title": title, "url": link, "extra": ""})
    return out


def send(msg):
    if not TOKEN or not CHAT_ID:
        print("텔레그램 토큰/챗ID 없음")
        return False
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://api.telegram.org/bot%s/sendMessage" % TOKEN, data=data), timeout=30) as r:
            return json.loads(r.read().decode()).get("ok") is True
    except urllib.error.HTTPError as e:
        try:
            print("텔레그램 오류:", json.loads(e.read().decode()).get("description"))
        except Exception:
            print("텔레그램 오류:", e)
    except Exception as e:
        print("텔레그램 오류:", e)
    return False


def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def run():
    if os.environ.get("SEND_TEST_NOTIFICATION", "false").lower() == "true":
        if not send("✅ [태권도 공고] 알리미 점검 완료\n텔레그램 알림 발송이 정상 동작합니다."):
            raise RuntimeError("텔레그램 테스트 알림 발송 실패")
        print("[발송 성공] 테스트")
        return

    items, errors = [], []
    for name, fn in (("KTA", kta_items), ("WTA", wta_items), ("KGTA", kgta_items)):
        try:
            got = fn()
            print(name, "후보", len(got))
            items += got
        except Exception as e:
            errors.append(f"{name}: {e}")
            print("수집 실패", name, e)

    history = load_history()
    failed = False
    for it in items:
        if it["id"] in history:
            continue
        lines = [f"📢 <b>[태권도 공고] {html.escape(it['src'])}</b>", "", html.escape(it["title"])]
        if it["extra"]:
            lines.append(html.escape(it["extra"]))
        lines += ["", f"🔗 <a href='{it['url']}'>상세보기</a>"]
        if send("\n".join(lines)):
            history.append(it["id"])
            print("[발송 성공]", it["id"])
        else:
            failed = True
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    if failed:
        raise RuntimeError("텔레그램 발송 실패 항목 있음")
    if errors:
        raise RuntimeError("수집 실패: " + "; ".join(errors))


if __name__ == "__main__":
    run()
