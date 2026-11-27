#!/usr/bin/env python3
"""Refresh jobs.json without Claude.

Runs on GitHub Actions (see .github/workflows/update-jobs.yml). It:
  1. drops jobs whose closing date has passed,
  2. searches GOV.UK Find a Job, Teaching Vacancies and Job Clerk for
     Hull / East Riding jobs of the kinds this site lists,
  3. opens each new advert to read pay, hours and the real closing date,
  4. adds the ones that pass the filters below and writes jobs.json.

Only the Python standard library is used.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_FILE = os.environ.get("JOBS_FILE") or os.path.join(ROOT, "jobs.json")
UA = "Mozilla/5.0 (compatible; kishis-job-finder/1.0; +https://github.com/Diniverse/kishis-job-finder)"
TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", "30"))
MAX_DETAILS = int(os.environ.get("MAX_DETAILS", "80"))
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()

# ---------------------------------------------------------------- filters
AREA = re.compile(
    r"\b(hull|kingston[- ]upon[- ]hull|cottingham|hessle|willerby|anlaby|kirk ella|sutton|bransholme|"
    r"hedon|beverley|goole|driffield|bridlington|hornsea|withernsea|brough|elloughton|welton|swanland|"
    r"north ferriby|cherry burton|leconfield|walkington|market weighton|howden|east riding|preston|"
    r"wawne|dunswell|skidby|gilberdyke|hu\d{1,2}|dn14|yo15|yo16|yo25)\b", re.I)
NOT_AREA = re.compile(r"\b(york|selby|doncaster|grimsby|scunthorpe|immingham|barton|lincoln|leeds|filey|scarborough|"
                      r"east halton|brigg|cleethorpes|north yorkshire|south yorkshire)\b", re.I)

CATEGORIES = [
    ("Healthcare Assistant", r"health ?care (assistant|support worker)|\bhca\b|\bhcsw\b|nursing assistant|clinical support worker|"
                             r"therap(y|ies) (assistant|helper)|imaging assistant|associate practitioner|assistant practitioner"),
    ("Pharmacy", r"pharmacy|dispenser|medicines (counter|optimisation)"),
    ("Lab & Phlebotomy", r"phlebotom|laboratory|lab assistant|pathology|specimen|sample collect"),
    ("Schools & SEN", r"teaching assistant|\bta\b|learning support|achievement support|\bsen\b|\bsend\b|\bhlta\b|"
                      r"learning assistant|1:1|one[- ]to[- ]one|achievement mentor|sen support|behaviour support"),
    ("Health Data & Digital", r"clinical cod|coding|data (administrator|assistant|officer)|digital (support|apprentic)|retinal screen"),
    ("Admin & Clerical", r"administrat|\badmin\b|ward clerk|receptionist|care navigator|medical secretar|patient services|"
                         r"medical records|clerk"),
    ("Care & Support", r"care assistant|carer\b|carers\b|care worker|support worker|personal assistant|\bpa\b|\bpas\b|"
                       r"care officer|direct payment|residential (care|support|childcare)|home care|domiciliary|"
                       r"care and support|reablement|enablement"),
]
EXCLUDE = re.compile(
    r"\b(nurse(?! assistant)|nursing associate|pharmacist|manager|director|head of|lead\b|consultant|doctor|"
    r"physiotherapist|occupational therapist|therapist\b|social worker|psycholog|cleaner|cleaning|domestic|housekeep|"
    r"kitchen|cook|chef|catering|driver|security|porter|maintenance|teacher\b|lecturer|instructor|finance|accountant|"
    r"recruitment|engineer|lunchtime|midday|caretaker|invigilator|exams officer|surveyor|sales|warehouse|"
    r"registered|qualified|deputy|coordinator of|registrar|locum|technician(?! apprentic))\b", re.I)
# admin roles count only in health, care or school settings
ADMIN_SETTING = re.compile(r"nhs|health|hospital|medical|practice|surgery|\bgp\b|cic|care|school|academy|primary|"
                           r"college|council|trust|pharmacy|clinic|hospice", re.I)


def categorise(title):
    if EXCLUDE.search(title):
        return None
    for cat, pat in CATEGORIES:
        if re.search(pat, title, re.I):
            return cat
    return None


def first_money(text):
    m = re.search(r"£\s?([\d,]+(?:\.\d+)?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def fit_for(cat, title, employer, pay):
    t = title.lower()
    money = first_money(pay)
    yearly = money if money and money > 1000 else None
    if re.search(r"\bhlta\b|higher level|band 4|associate practitioner|assistant practitioner|senior support|"
                 r"apprentice.*technician", t) or (yearly and yearly >= 28000):
        return "stretch"
    if cat in ("Healthcare Assistant", "Care & Support", "Lab & Phlebotomy"):
        return "strong"
    if cat == "Pharmacy":
        return "strong" if re.search(r"nhs|hospital|trust", employer, re.I) else "good"
    if cat == "Admin & Clerical":
        return "good" if (yearly and yearly >= 25700) or "senior" in t else "strong"
    return "good"


# ---------------------------------------------------------------- helpers
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:  # network errors are reported, never fatal
        print(f"  ! {url}: {e}", file=sys.stderr)
        return None
    finally:
        time.sleep(1)


def text_lines(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [l.strip() for l in t.split("\n") if l.strip()]


def after(lines, label, n=1):
    for i, l in enumerate(lines):
        if l.rstrip(":").lower() == label.rstrip(":").lower() and i + n < len(lines):
            return lines[i + n]
    return ""


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", s or "")
    if not m or m.group(2).lower()[:3] not in MONTHS:
        return ""
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1))).isoformat()
    except ValueError:
        return ""


def slug(s, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:n].strip("-")


def summarise(text, title, employer, location):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or re.match(r"(for further|please (see|refer)|see attached|for more information)", text, re.I):
        return f"{title} with {employer} in {location}; see the advert for duties and requirements."
    sents = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sents:
        if len(out) + len(s) > 260:
            break
        out = (out + " " + s).strip()
    return out or text[:260].rsplit(" ", 1)[0] + "…"


def is_open(job, max_age=60):
    """Open if the closing date hasn't passed; with no closing date, if posted within max_age days."""
    c = job.get("closes") or ""
    if c:
        return c >= TODAY.isoformat()
    p = job.get("posted") or ""
    return not p or (TODAY - dt.date.fromisoformat(p)).days <= max_age


# ---------------------------------------------------------------- sources
FAJ_WORDS = ["care assistant", "support worker", "healthcare", "care worker", "NHS", "pharmacy",
             "administrator", "receptionist", "teaching assistant"]
FAJ_TOWNS = ["Hull", "Beverley", "Bridlington", "Goole"]


def faj_candidates():
    seen = {}
    for town in FAJ_TOWNS:
        for word in FAJ_WORDS:
            page = fetch("https://www.jobs.service.gov.uk/jobs/search?keywords="
                         + urllib.request.quote(word) + "&location=" + town)
            if not page:
                continue
            for card in page.split('data-testid="searchResultCard-')[1:]:
                jid = card[:24]
                t = re.search(r"<h2[^>]*>(.*?)</h2>", card, re.S)
                e = re.search(r'searchResultCardEmployer"><span>(.*?)</span>(?:<span[^>]*>(.*?)</span>)?', card, re.S)
                if not t:
                    continue
                title = html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
                emp = html.unescape(e.group(1)).strip() if e else ""
                loc = html.unescape(re.sub(r"^\s*-\s*", "", e.group(2) or "")).strip() if e else ""
                seen.setdefault(jid, (title, emp, loc))
    return [("faj", jid, f"https://www.jobs.service.gov.uk/jobs/{jid}", *v) for jid, v in seen.items()]


def faj_detail(url):
    page = fetch(url)
    if not page:
        return None
    L = text_lines(page)
    body = " ".join(L)
    closes = parse_date(after(L, "Closing date:"))
    real = re.search(r"advert closes on \w+ (\d{1,2} \w+ \d{4})", body)
    if real:
        closes = parse_date(real.group(1))  # NHS adverts: header date is often later than the real one
    summ = ""
    if "Summary" in L:
        i = L.index("Summary")
        summ = " ".join(L[i + 1:i + 12]).split("Apply for this job")[0]
    return {"employer": after(L, "Company:"), "pay": after(L, "Salary:"), "hours": after(L, "Hours:"),
            "location": after(L, "Location:"), "type": after(L, "Job type:"),
            "posted": parse_date(after(L, "Posting date:")), "closes": closes, "summary": summ}


TV_ORGS = [("kingston-upon-hull-city-of-local-authority", 6), ("east-riding-of-yorkshire-local-authority", 3)]


def tv_candidates():
    out = {}
    for org, pages in TV_ORGS:
        for p in range(1, pages + 1):
            page = fetch(f"https://teaching-vacancies.service.gov.uk/organisations/{org}?page={p}")
            if not page:
                continue
            for m in re.finditer(r'href="(/jobs/[^"?#]+)"[^>]*>(.*?)</a>', page, re.S):
                title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if title:
                    out.setdefault(m.group(1), title)
    return [("tv", path, "https://teaching-vacancies.service.gov.uk" + path, title, "", "") for path, title in out.items()]


def tv_detail(url):
    page = fetch(url)
    if not page:
        return None
    L = text_lines(page)
    place = ""
    for i, l in enumerate(L):
        if l == "Get a job alert for similar jobs":
            back = [x for x in L[max(0, i - 3):i] if "," in x and "advert" not in x.lower()]
            place = back[-1] if back else ""
            break
    employer, _, location = place.partition(",")
    summ = ""
    for i, l in enumerate(L):
        if l.lower().endswith("job summary"):
            summ = " ".join(L[i + 1:i + 8])
            break
    pay = after(L, "Full time equivalent salary") or after(L, "Actual salary")
    hours = " ".join(x for x in [after(L, "Working pattern"), after(L, "Contract type")] if x)
    return {"employer": employer.strip(), "location": location.strip(" ,"), "pay": pay, "hours": hours,
            "posted": parse_date(after(L, "Date listed")), "closes": parse_date(after(L, "Closing date")),
            "summary": summ}


def jc_candidates():
    out = {}
    for p in (1, 2):
        page = fetch("https://www.jobclerk.com/jobs-in/hull" + ("" if p == 1 else "?page=2"))
        if not page:
            continue
        for m in re.finditer(r'href="(/job/[^"/]+/[0-9a-f-]{36})"[^>]*>(.*?)</a>', page, re.S):
            parts = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "|", m.group(2))).split("|") if x.strip()]
            if parts:
                out.setdefault(m.group(1), (parts[0], parts[1] if len(parts) > 1 else ""))
    return [("jc", path, "https://www.jobclerk.com" + path, t, e, "Hull") for path, (t, e) in out.items()]


def jc_detail(url):
    page = fetch(url)
    if not page:
        return None
    L = text_lines(page)
    grade = after(L, "Grade")
    if re.search(r"band\s*([5-9])", grade, re.I):
        return {"skip": True}
    summ = ""
    if "Job overview" in L:
        i = L.index("Job overview")
        summ = " ".join(L[i + 1:i + 6])
    return {"employer": "", "location": after(L, "Location") or "Hull", "pay": after(L, "Salary"),
            "hours": after(L, "Contract Type"), "posted": parse_date(after(L, "Posted Date")),
            "closes": parse_date(after(L, "Deadline")), "summary": summ}


DETAIL = {"faj": faj_detail, "tv": tv_detail, "jc": jc_detail}
SOURCE = {"faj": "GOV.UK Find a Job", "tv": "Teaching Vacancies", "jc": "Job Clerk"}


# ---------------------------------------------------------------- main
def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def alt_key(j):
    """Same advert listed under a different employer name: title start + postcode + closing date."""
    pc = re.search(r"\b([A-Z]{1,2}\d{1,2}\s*\d[A-Z]{2})\b", j.get("location") or "", re.I)
    return "alt:" + norm(j.get("title"))[:10] + (norm(pc.group(1)) if pc else norm(j.get("location"))[:12]) + (j.get("closes") or "")


def main():
    data = json.load(open(JOBS_FILE, encoding="utf-8"))
    jobs = [j for j in data.get("jobs", []) if is_open(j)]
    dropped = len(data.get("jobs", [])) - len(jobs)
    known_urls = {j["url"].split("?")[0] for j in data.get("jobs", [])}
    known_ids = {j["id"] for j in data.get("jobs", [])}
    known_keys = {norm(j["employer"])[:20] + norm(j["title"])[:30] for j in data.get("jobs", [])}
    known_keys |= {alt_key(j) for j in data.get("jobs", [])}

    cands = []
    for name, fn in (("Find a Job", faj_candidates), ("Teaching Vacancies", tv_candidates), ("Job Clerk", jc_candidates)):
        found = fn()
        print(f"{name}: {len(found)} listings")
        cands += found

    added, checked = [], 0
    for src, ref, url, title, emp, loc in cands:
        if url in known_urls or checked >= MAX_DETAILS:
            continue
        cat = categorise(title)
        if not cat:
            continue
        if loc and (NOT_AREA.search(loc) and not AREA.search(loc)):
            continue
        checked += 1
        d = DETAIL[src](url)
        known_urls.add(url)
        if not d or d.get("skip"):
            continue
        employer = d.get("employer") or emp or "Employer not named"
        if employer == "NHS Jobs":
            employer = emp if emp and emp != "NHS Jobs" else "NHS employer (advertised via NHS Jobs)"
        location = d.get("location") or loc
        if not AREA.search(location) or (NOT_AREA.search(location) and not re.search(r"\bhu\d", location, re.I)):
            continue
        if cat == "Admin & Clerical" and not ADMIN_SETTING.search(employer + " " + title):
            continue
        money = first_money(d.get("pay"))
        if money and money >= 32000 and "fte" not in (d.get("pay") or "").lower():
            continue  # Band 5 and above
        job = {"title": title, "employer": employer, "location": location, "pay": d.get("pay", ""),
               "hours": " ".join(x for x in [d.get("hours", ""), d.get("type", "")] if x).strip(),
               "category": cat, "closes": d.get("closes", ""), "posted": d.get("posted", ""), "url": url,
               "source": SOURCE[src]}
        if not is_open(job, max_age=21):
            continue
        key = norm(employer)[:20] + norm(title)[:30]
        if key in known_keys or alt_key(job) in known_keys:
            continue
        tail = (ref.rstrip("/").split("/")[-1])[:8] if src != "tv" else slug(ref.split("/")[-1][-12:], 12)
        jid = "-".join(x for x in [slug(employer, 30), slug(title, 40), slug(location.split(",")[0], 15), slug(tail, 12)] if x)
        if jid in known_ids:
            continue
        job = {"id": jid, **job, "fit": fit_for(cat, title, employer, job["pay"]),
               "addedAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "why": summarise(d.get("summary"), title, employer, location)}
        added.append(job)
        known_ids.add(jid)
        known_keys.add(key)
        known_keys.add(alt_key(job))
        print(f"  + {title} | {employer} | {location} | closes {job['closes'] or '?'}")

    out = {"updatedAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "jobs": added + jobs}
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Added {len(added)}, dropped {dropped} closed, {len(out['jobs'])} open jobs now.")


if __name__ == "__main__":
    main()
