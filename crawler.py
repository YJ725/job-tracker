import re
import json
import requests
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_DESC_LENGTH = 3000


def detect_site(url):
    """URL에서 사이트를 판별한다."""
    if "saramin.co.kr" in url:
        return "saramin"
    if "jobkorea.co.kr" in url:
        return "jobkorea"
    if "wanted.co.kr" in url:
        return "wanted"
    raise ValueError("지원하지 않는 사이트입니다. 사람인, 잡코리아, 원티드 URL만 가능합니다.")


def truncate(text, limit=MAX_DESC_LENGTH):
    if text and len(text) > limit:
        return text[:limit] + "..."
    return text


def _empty_detail_fields():
    """상세 필드 기본값 딕셔너리."""
    return {
        "deadline": "",
        "experience": "",
        "education": "",
        "salary": "",
        "location": "",
        "requirements": "",
    }


# ---------------------------------------------------------------------------
# 개별 공고 크롤링 (기존 + 상세 필드 확장)
# ---------------------------------------------------------------------------

def crawl_job(url):
    """메인 크롤링 함수. 사이트별 파서를 디스패치한다."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    site = detect_site(url)

    if site == "wanted":
        return crawl_wanted(url)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"페이지를 불러올 수 없습니다: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    if site == "saramin":
        return parse_saramin(soup, url)
    if site == "jobkorea":
        return parse_jobkorea(soup, url)


def parse_saramin(soup, url):
    """사람인 채용공고 HTML 파싱."""
    title = ""
    company = ""
    description = ""
    detail = _empty_detail_fields()

    title_el = (
        soup.select_one(".jv_title .tit_job")
        or soup.select_one("h1.title")
        or soup.select_one("meta[property='og:title']")
    )
    if title_el:
        title = title_el.get("content", "") if title_el.name == "meta" else title_el.get_text(strip=True)

    company_el = (
        soup.select_one(".jv_header .company a")
        or soup.select_one(".jv_company .name")
        or soup.select_one("meta[property='og:article:author']")
    )
    if company_el:
        company = company_el.get("content", "") if company_el.name == "meta" else company_el.get_text(strip=True)

    desc_el = (
        soup.select_one(".jv_detail .cont")
        or soup.select_one(".jv_detail")
        or soup.select_one("#job_detail")
    )
    if desc_el:
        description = desc_el.get_text(separator="\n", strip=True)

    if not title or not company:
        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            parts = og["content"].split(" - ")
            if not company and len(parts) >= 2:
                company = parts[0].strip()
            if not title and len(parts) >= 2:
                title = parts[1].strip()
            elif not title:
                title = og["content"].strip()

    for col in soup.select(".jv_cont .col"):
        header = col.select_one("dt, .tit")
        value = col.select_one("dd, .desc")
        if not header or not value:
            continue
        h = header.get_text(strip=True)
        v = value.get_text(" ", strip=True)
        if "경력" in h:
            detail["experience"] = v
        elif "학력" in h:
            detail["education"] = v
        elif "급여" in h or "연봉" in h:
            detail["salary"] = v
        elif "근무지" in h or "지역" in h:
            detail["location"] = v
        elif "마감" in h or "기간" in h:
            detail["deadline"] = v

    req_el = soup.select_one(".jv_detail .cont")
    if req_el:
        req_text = req_el.get_text(separator="\n", strip=True)
        for marker in ["자격요건", "자격 요건", "우대사항", "우대 사항"]:
            if marker in req_text:
                detail["requirements"] = req_text
                break

    if not detail["location"]:
        loc_meta = soup.select_one("meta[property='og:locality']")
        if loc_meta and loc_meta.get("content"):
            detail["location"] = loc_meta["content"]

    return {
        "title": title,
        "company": company,
        "url": url,
        "description": truncate(description),
        **detail,
    }


def parse_jobkorea(soup, url):
    """잡코리아 채용공고 HTML 파싱 + __NEXT_DATA__ JSON 폴백."""
    title = ""
    company = ""
    description = ""
    detail = _empty_detail_fields()

    next_data_el = soup.select_one("script#__NEXT_DATA__")
    if next_data_el and next_data_el.string:
        try:
            data = json.loads(next_data_el.string)
            props = data.get("props", {}).get("pageProps", {})
            dd = props.get("detailData", {})

            title = dd.get("gioTitle", "") or dd.get("title", "")
            company = (
                dd.get("companyName", "")
                or props.get("companyData", {}).get("name", "")
            )
            description = dd.get("detail", "") or dd.get("jobDescription", "")

            detail["experience"] = dd.get("experience", "") or dd.get("career", "")
            detail["education"] = dd.get("education", "") or dd.get("degree", "")
            detail["salary"] = dd.get("salary", "") or dd.get("salaryType", "")
            detail["location"] = dd.get("location", "") or dd.get("workPlace", "")
            detail["deadline"] = dd.get("deadline", "") or dd.get("closingDate", "")
            detail["requirements"] = dd.get("requirements", "") or dd.get("qualifications", "")

            if title:
                return {
                    "title": title,
                    "company": company,
                    "url": url,
                    "description": truncate(description),
                    **detail,
                }
        except (json.JSONDecodeError, KeyError):
            pass

    title_el = (
        soup.select_one(".artReadJobTitle h3")
        or soup.select_one(".sumTit")
        or soup.select_one("meta[property='og:title']")
    )
    if title_el:
        title = title_el.get("content", "") if title_el.name == "meta" else title_el.get_text(strip=True)

    company_el = (
        soup.select_one(".artReadCompanyName a")
        or soup.select_one(".coName")
        or soup.select_one("meta[property='og:article:author']")
    )
    if company_el:
        company = company_el.get("content", "") if company_el.name == "meta" else company_el.get_text(strip=True)

    desc_el = (
        soup.select_one(".artReadDetail")
        or soup.select_one("#duty_section")
    )
    if desc_el:
        description = desc_el.get_text(separator="\n", strip=True)

    for row in soup.select(".artReadJobInfo .tbRow"):
        header = row.select_one("th, .tHead")
        value = row.select_one("td, .tData")
        if not header or not value:
            continue
        h = header.get_text(strip=True)
        v = value.get_text(" ", strip=True)
        if "경력" in h:
            detail["experience"] = v
        elif "학력" in h:
            detail["education"] = v
        elif "급여" in h or "연봉" in h:
            detail["salary"] = v
        elif "근무지" in h or "지역" in h:
            detail["location"] = v
        elif "마감" in h or "기간" in h:
            detail["deadline"] = v

    if not title:
        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            title = og["content"].strip()

    return {
        "title": title,
        "company": company,
        "url": url,
        "description": truncate(description),
        **detail,
    }


def crawl_wanted(url):
    """원티드 크롤링. API 우선, HTML 폴백."""
    match = re.search(r"/wd/(\d+)", url)
    if not match:
        raise ValueError("원티드 채용공고 URL 형식이 올바르지 않습니다. (예: https://www.wanted.co.kr/wd/12345)")

    job_id = match.group(1)
    detail = _empty_detail_fields()

    api_url = f"https://www.wanted.co.kr/api/v4/jobs/{job_id}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        job = data.get("job", {})

        title = job.get("position", "")
        company = job.get("company", {}).get("name", "")

        desc_parts = []
        if job.get("intro"):
            desc_parts.append(job["intro"])
        if job.get("main_tasks"):
            desc_parts.append("[주요업무]\n" + job["main_tasks"])
        if job.get("requirements"):
            desc_parts.append("[자격요건]\n" + job["requirements"])
        if job.get("preferred"):
            desc_parts.append("[우대사항]\n" + job["preferred"])
        if job.get("benefits"):
            desc_parts.append("[혜택 및 복지]\n" + job["benefits"])
        description = "\n\n".join(desc_parts)

        detail["experience"] = job.get("experience_level", "")
        detail["location"] = job.get("company", {}).get("location", "")
        detail["deadline"] = job.get("due_time", "")
        detail["requirements"] = job.get("requirements", "")
        detail["salary"] = job.get("salary", "")
        detail["education"] = job.get("education", "")

        if title:
            return {
                "title": title,
                "company": company,
                "url": url,
                "description": truncate(description),
                **detail,
            }
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        pass

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"페이지를 불러올 수 없습니다: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    title = ""
    company = ""
    description = ""

    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        parts = og_title["content"].rsplit(" - ", 1)
        title = parts[0].strip()
        if len(parts) >= 2:
            company = parts[1].strip()

    og_desc = soup.select_one("meta[property='og:description']")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()

    return {
        "title": title,
        "company": company,
        "url": url,
        "description": truncate(description),
        **detail,
    }


# ---------------------------------------------------------------------------
# 키워드 검색 기능 (멀티페이지 + source 필드)
# ---------------------------------------------------------------------------

def _parse_saramin_condition(text):
    """사람인 조건 텍스트를 필드로 분류."""
    LOCATIONS = [
        "서울", "경기", "인천", "부산", "대구", "광주", "대전",
        "울산", "세종", "강원", "충북", "충남", "전북", "전남",
        "경북", "경남", "제주",
    ]
    EDUCATIONS = ["대졸", "초대졸", "고졸", "석사", "박사", "학력"]

    if any(loc in text for loc in LOCATIONS):
        return "location"
    if "경력" in text or "신입" in text:
        return "experience"
    if any(edu in text for edu in EDUCATIONS):
        return "education"
    return None


def _extract_total_number(text):
    """'총 1,685건' 같은 텍스트에서 숫자만 추출."""
    m = re.search(r"[\d,]+", text.replace(" ", ""))
    if m:
        return int(m.group().replace(",", ""))
    return 0


def search_saramin(keyword, start_page=1, end_page=5):
    """사람인 키워드 검색 → 페이지 범위 크롤링."""
    results = []
    seen = set()
    pages_crawled = 0
    first_page = start_page
    last_page = start_page
    has_more = False
    total_jobs = 0
    total_pages = 0
    per_page = 40

    page = start_page - 1
    while True:
        page += 1
        if end_page and page > end_page:
            has_more = total_pages > end_page if total_pages else True
            break

        search_url = (
            f"https://www.saramin.co.kr/zf_user/search/recruit"
            f"?searchword={quote_plus(keyword)}&recruitPage={page}"
        )
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(".item_recruit")
        if not items:
            break

        # 첫 번째로 가져온 페이지에서 전체 건수 파싱
        if pages_crawled == 0:
            cnt_el = soup.select_one(".cnt_result")
            if cnt_el:
                total_jobs = _extract_total_number(cnt_el.get_text())
            if total_jobs > 0:
                total_pages = -(-total_jobs // per_page)

        pages_crawled += 1
        last_page = page

        for item in items:
            detail = _empty_detail_fields()
            title_el = item.select_one(".job_tit a")
            company_el = item.select_one(".corp_name a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.saramin.co.kr" + href

            if not href or href in seen:
                continue
            seen.add(href)

            company = company_el.get_text(strip=True) if company_el else ""

            conditions = item.select(".job_condition span")
            for cond in conditions:
                text = cond.get_text(strip=True)
                if not text:
                    continue
                field = _parse_saramin_condition(text)
                if field:
                    detail[field] = text

            deadline_el = item.select_one(".job_date .date")
            if deadline_el:
                detail["deadline"] = deadline_el.get_text(strip=True)

            results.append({
                "title": title,
                "company": company,
                "url": href,
                "description": "",
                "source": "사람인",
                **detail,
            })

    if not has_more and total_pages and page < total_pages:
        has_more = True

    return {
        "results": results,
        "pages_crawled": pages_crawled,
        "first_page": first_page,
        "last_page": last_page,
        "has_more": has_more,
        "total_jobs": total_jobs,
        "total_pages": total_pages,
    }


def _parse_jobkorea_spans(spans):
    """잡코리아 카드 내 span 텍스트를 상세 필드로 분류."""
    detail = _empty_detail_fields()
    deadline_parts = []

    for s in spans:
        text = s.get_text(strip=True)
        if not text or len(text) > 60 or text == "스크랩" or text == "•":
            continue
        if "경력" in text or "신입" in text:
            detail["experience"] = text
        elif any(loc in text for loc in [
            "서울", "경기", "인천", "부산", "대구", "광주", "대전",
            "울산", "세종", "강원", "충북", "충남", "전북", "전남",
            "경북", "경남", "제주",
        ]):
            # 지역은 짧은 텍스트만 (직종 설명과 구분)
            if len(text) < 15:
                detail["location"] = text
        elif "마감" in text or "등록" in text:
            deadline_parts.append(text)

    if deadline_parts:
        detail["deadline"] = " / ".join(deadline_parts)

    return detail


def search_jobkorea(keyword, start_page=1, end_page=5):
    """잡코리아 키워드 검색 → 페이지 범위 크롤링."""
    results = []
    seen = set()
    pages_crawled = 0
    first_page = start_page
    last_page = start_page
    has_more = False
    total_jobs = 0
    total_pages = 0
    per_page = 25

    page = start_page - 1
    while True:
        page += 1
        if end_page and page > end_page:
            has_more = total_pages > end_page if total_pages else True
            break

        search_url = (
            f"https://www.jobkorea.co.kr/Search/"
            f"?stext={quote_plus(keyword)}&tabType=recruit&Page_No={page}"
        )
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.dlua7o0")
        if not cards:
            break

        # 첫 번째로 가져온 페이지에서 전체 건수 파싱
        if pages_crawled == 0:
            for span in soup.select("span"):
                text = span.get_text(strip=True)
                if "총" in text and "건" in text:
                    total_jobs = _extract_total_number(text)
                    if total_jobs > 0:
                        total_pages = -(-total_jobs // per_page)
                    break

        pages_crawled += 1
        last_page = page

        for card in cards:
            recruit_links = card.select('a[href*="/Recruit/"]')
            title = ""
            company = ""
            href = ""

            for a in recruit_links:
                text = a.get_text(strip=True)
                h = a.get("href", "")
                if not text:
                    continue
                if not title:
                    title = text
                    href = h
                elif not company:
                    company = text

            if not title or not href:
                continue

            if not href.startswith("http"):
                href = "https://www.jobkorea.co.kr" + href

            clean_href = href.split("?")[0]
            if clean_href in seen:
                continue
            seen.add(clean_href)

            spans = card.select("span")
            detail = _parse_jobkorea_spans(spans)

            results.append({
                "title": title,
                "company": company,
                "url": href,
                "description": "",
                "source": "잡코리아",
                **detail,
            })

    if not has_more and total_pages and page < total_pages:
        has_more = True

    return {
        "results": results,
        "pages_crawled": pages_crawled,
        "first_page": first_page,
        "last_page": last_page,
        "has_more": has_more,
        "total_jobs": total_jobs,
        "total_pages": total_pages,
    }


def search_wanted(keyword, start_page=1, end_page=5):
    """원티드 키워드 검색 (API) → 페이지 범위 크롤링.
    원티드 API는 전체 건수를 제공하지 않으므로 페이지 끝 도달 시에만 확정.
    """
    results = []
    seen = set()
    limit = 20
    pages_crawled = 0
    first_page = start_page
    last_page = start_page
    has_more = False
    total_jobs = 0
    total_pages = 0
    reached_end = False

    page = start_page - 1
    while True:
        page += 1
        offset = (page - 1) * limit

        if end_page and page > end_page:
            # 다음 페이지 존재 여부만 확인
            probe_url = (
                f"https://www.wanted.co.kr/api/v4/jobs"
                f"?country=kr&query={quote_plus(keyword)}&limit=1&offset={offset}"
            )
            try:
                resp = requests.get(probe_url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("data"):
                    has_more = True
            except (requests.RequestException, json.JSONDecodeError):
                pass
            break

        api_url = (
            f"https://www.wanted.co.kr/api/v4/jobs"
            f"?country=kr&query={quote_plus(keyword)}&limit={limit}&offset={offset}"
        )
        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            break

        items = data.get("data", [])
        if not items:
            reached_end = True
            break

        pages_crawled += 1
        last_page = page

        for item in items:
            detail = _empty_detail_fields()
            job_id = item.get("id", "")
            title = item.get("position", "")
            company = item.get("company", {}).get("name", "")
            url = f"https://www.wanted.co.kr/wd/{job_id}" if job_id else ""

            if not title or not url or url in seen:
                continue
            seen.add(url)

            detail["location"] = item.get("address", {}).get("full_location", "")
            if not detail["location"]:
                detail["location"] = item.get("company", {}).get("location", "")
            detail["experience"] = item.get("experience_level", "")
            detail["deadline"] = item.get("due_time", "")

            results.append({
                "title": title,
                "company": company,
                "url": url,
                "description": "",
                "source": "원티드",
                **detail,
            })

        if len(items) < limit:
            reached_end = True
            break

    if reached_end:
        total_jobs = len(results)
        total_pages = last_page if pages_crawled > 0 else 0

    return {
        "results": results,
        "pages_crawled": pages_crawled,
        "first_page": first_page,
        "last_page": last_page,
        "has_more": has_more,
        "total_jobs": total_jobs,
        "total_pages": total_pages,
    }


def search_all(keyword, start_page=1, end_page=5, sites=None):
    """3개 사이트 통합 검색.
    end_page=None 이면 전체 크롤링 (제한 없음).
    sites: 검색할 사이트 이름 리스트. None이면 전체.
    """
    all_results = []
    seen_urls = set()
    site_info = {}

    search_fns = [
        ("사람인", search_saramin),
        ("잡코리아", search_jobkorea),
        ("원티드", search_wanted),
    ]

    for site_name, search_fn in search_fns:
        if sites is not None and site_name not in sites:
            continue

        try:
            data = search_fn(keyword, start_page=start_page, end_page=end_page)
        except Exception:
            site_info[site_name] = {
                "count": 0, "pages_crawled": 0, "first_page": start_page,
                "last_page": start_page, "has_more": False, "error": True,
                "total_jobs": 0, "total_pages": 0,
            }
            continue

        count = 0
        for item in data["results"]:
            if item["url"] and item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_results.append(item)
                count += 1

        site_info[site_name] = {
            "count": count,
            "pages_crawled": data["pages_crawled"],
            "first_page": data.get("first_page", start_page),
            "last_page": data.get("last_page", start_page),
            "has_more": data["has_more"],
            "total_jobs": data.get("total_jobs", 0),
            "total_pages": data.get("total_pages", 0),
        }

    return {"results": all_results, "site_info": site_info}
