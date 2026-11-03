#!/usr/bin/env python3
"""Correzione autonoma delle vulnerabilità pip (security-autofix.yml).

Per ogni lock con hash del repo esegue pip-audit, tiene le vulnerabilità
HIGH/CRITICAL (severità da OSV) con versione corretta e sceglie, per pacchetto,
la versione più bassa che corregge e che:
  - è pubblicata su PyPI da almeno MIN_AGE (48 h; --force salta solo questo);
  - ha provenienza PEP 740 attestata da PyPI e pubblicata dallo STESSO
    repository della versione attualmente nel lock (mai saltato).
La correzione è un pin nel file .in (diretta: versione aggiornata;
transitiva: riga nuova con commento e condizione di rimozione); il lock si
rigenera con scripts/compile-requirements.sh.

Gruppi: "auto" (auto-merge in coda) e "manual" (librerie SPID/CIE: solo PR,
revisione umana, vedi docs/superpowers/specs/2026-11-03-...-design.md §2.3).

Uso:
  pip_fix.py plan  --output plan.json [--force]
  pip_fix.py apply --plan plan.json --group auto|manual
Solo libreria standard: gira con la Python del runner, senza dipendenze.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[2]
MIN_AGE = dt.timedelta(hours=48)
PIP_AUDIT = "pip-audit==2.10.1"

# Firma/identità SPID SAML e CIE: mai auto-merge.
MANUAL = {"pysaml2", "cryptojwt", "cryptography", "pyeudiw", "satosa", "pyop"}


@dataclasses.dataclass(frozen=True)
class Target:
    lock: str  # percorso relativo del lock con hash
    infile: str  # .in da modificare
    parent_lock: str | None = None  # lock "padre" (dev → runtime): chi è lì si corregge là


TARGETS = [
    Target("config-api/requirements.txt", "config-api/requirements.in"),
    Target("config-api/requirements-dev.txt", "config-api/requirements-dev.in",
           parent_lock="config-api/requirements.txt"),
    Target("satosa/requirements-runtime.txt", "satosa/requirements-runtime.in"),
    Target("satosa/tests/requirements-test.txt", "satosa/tests/requirements-test.in"),
]

HttpGet = Callable[[str], dict | None]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def version_key(v: str) -> tuple:
    """Ordinamento PEP 440 semplificato (release numerica, pre/post release)."""
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((), v)
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (6 - len(nums))
    rest = m.group(2)
    # pre-release (a/b/rc/dev) < release < post-release
    if re.match(r"^\.?(dev|a|b|rc)", rest):
        return (nums, 0, rest)
    if rest == "":
        return (nums, 1, "")
    return (nums, 2, rest)


def parse_lock(text: str) -> dict[str, str]:
    pins = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if m:
            pins[normalize(m.group(1))] = m.group(2)
    return pins


def http_get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "pa-sso-proxy-security-autofix"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def severity(vuln_ids: Iterable[str], get: HttpGet) -> str:
    """Severità più alta tra gli ID (GHSA/PYSEC/CVE) secondo OSV; UNKNOWN se assente."""
    order = ["LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"]
    best = "UNKNOWN"
    for vid in vuln_ids:
        data = get(f"https://api.osv.dev/v1/vulns/{urllib.parse.quote(vid)}")
        if not data:
            continue
        sev = str((data.get("database_specific") or {}).get("severity", "")).upper()
        if sev in order and (best == "UNKNOWN" or order.index(sev) > order.index(best)):
            best = sev
    return best


def release_files(name: str, version: str, get: HttpGet) -> list[dict]:
    data = get(f"https://pypi.org/pypi/{name}/{version}/json")
    return (data or {}).get("urls", [])


def upload_time(files: list[dict]) -> dt.datetime | None:
    times = [dt.datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00"))
             for f in files if f.get("upload_time_iso_8601")]
    return min(times) if times else None


def provenance_repos(name: str, version: str, files: list[dict], get: HttpGet) -> set[str]:
    """Repository dei publisher PEP 740 (attestazioni verificate da PyPI all'upload)."""
    repos: set[str] = set()
    for f in files:
        prov = get(f"https://pypi.org/integrity/{name}/{version}/{f['filename']}/provenance")
        for bundle in (prov or {}).get("attestation_bundles", []):
            pub = bundle.get("publisher") or {}
            if pub.get("repository"):
                repos.add(f"{pub.get('kind', '?')}:{pub['repository'].lower()}")
    return repos


@dataclasses.dataclass
class Choice:
    version: str | None
    status: str  # ok | pending | unfixable
    reason: str


def choose_version(name: str, current: str, fix_versions: list[str], now: dt.datetime,
                   get: HttpGet, force: bool = False) -> Choice:
    candidates = sorted((v for v in fix_versions if version_key(v) > version_key(current)),
                        key=version_key)
    if not candidates:
        return Choice(None, "unfixable", "nessuna versione corretta più recente di quella nel lock")
    cand = candidates[0]
    files = release_files(name, cand, get)
    if not files:
        return Choice(None, "unfixable", f"{cand} non trovata su PyPI")
    published = upload_time(files)
    if published and not force and now - published < MIN_AGE:
        return Choice(None, "pending",
                      f"{cand} pubblicata il {published:%Y-%m-%d %H:%M} UTC, meno di 48 h fa")
    cur_repos = provenance_repos(name, current, release_files(name, current, get), get)
    if not cur_repos:
        return Choice(None, "unfixable",
                      f"{current} senza provenienza PEP 740: impossibile verificare l'origine di {cand}")
    new_repos = provenance_repos(name, cand, files, get)
    if not new_repos:
        return Choice(None, "unfixable", f"{cand} senza provenienza PEP 740")
    if not new_repos <= cur_repos:
        return Choice(None, "unfixable",
                      f"provenienza di {cand} ({', '.join(sorted(new_repos))}) diversa da "
                      f"{current} ({', '.join(sorted(cur_repos))})")
    return Choice(cand, "ok", f"{current} → {cand}, provenienza {', '.join(sorted(new_repos))}")


def edit_infile(text: str, name: str, version: str, advisories: list[str]) -> str:
    """Pin nel file .in: aggiorna la riga della dipendenza diretta o aggiunge un pin transitivo."""
    norm = normalize(name)
    adv = ", ".join(advisories)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*([<>=!~].*?)?(\s*#.*)?$",
                     line.rstrip("\n"))
        if m and normalize(m.group(1)) == norm:
            extras = m.group(2) or ""
            lines[i] = f"{m.group(1)}{extras}=={version}  # security-autofix: {adv}\n"
            return "".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    return (text
            + f"# security-autofix ({adv}): dipendenza transitiva fissata alla versione corretta.\n"
            + f"# Rimuovere quando il pacchetto che la richiede impone già >= {version}.\n"
            + f"{name}=={version}\n")


def run_pip_audit(lock: pathlib.Path) -> list[dict]:
    """pip-audit su un lock con hash; restituisce [{name, version, id, aliases, fix_versions}]."""
    proc = subprocess.run(
        ["pipx", "run", "--spec", PIP_AUDIT, "pip-audit", "--require-hashes", "--disable-pip",
         "--format", "json", "--progress-spinner", "off", "-r", str(lock)],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"pip-audit {lock}: {proc.stderr.strip()[-2000:]}")
    return parse_audit(json.loads(proc.stdout or "{}"))


def parse_audit(data: dict) -> list[dict]:
    out = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            out.append({"name": dep["name"], "version": dep["version"], "id": v["id"],
                        "aliases": v.get("aliases", []), "fix_versions": v.get("fix_versions", [])})
    return out


def build_plan(findings: dict[str, list[dict]], locks: dict[str, str], now: dt.datetime,
               get: HttpGet, force: bool = False) -> dict:
    """findings: lock → risultati pip-audit; locks: lock → testo del lock."""
    by_target: dict[tuple[str, str], dict] = {}
    for target in TARGETS:
        parent = parse_lock(locks.get(target.parent_lock, "")) if target.parent_lock else {}
        for f in findings.get(target.lock, []):
            norm = normalize(f["name"])
            if norm in parent:  # si corregge nel lock padre (stessa versione, vincolo -c)
                continue
            key = (target.infile, norm)
            entry = by_target.setdefault(key, {"infile": target.infile, "lock": target.lock,
                                               "name": f["name"], "current": f["version"],
                                               "advisories": [], "fix_versions": set()})
            entry["advisories"].append(f["id"])
            entry["fix_versions"].update(f["fix_versions"])
            entry.setdefault("ids", []).extend([f["id"], *f["aliases"]])
    plan = {"auto": [], "manual": [], "pending": [], "unfixable": []}
    for entry in by_target.values():
        sev = severity(entry.pop("ids"), get)
        if sev not in ("HIGH", "CRITICAL", "UNKNOWN"):
            continue
        choice = choose_version(entry["name"], entry["current"], sorted(entry["fix_versions"]),
                                now, get, force=force)
        item = {k: v for k, v in entry.items() if k != "fix_versions"}
        item.update(severity=sev, version=choice.version, reason=choice.reason,
                    advisories=sorted(set(entry["advisories"])))
        if choice.status == "ok":
            plan["manual" if normalize(entry["name"]) in MANUAL else "auto"].append(item)
        else:
            plan[choice.status].append(item)
    for k in plan:
        plan[k].sort(key=lambda i: (i["infile"], normalize(i["name"])))
    return plan


def cmd_plan(args) -> int:
    findings, locks = {}, {}
    for t in TARGETS:
        path = ROOT / t.lock
        locks[t.lock] = path.read_text(encoding="utf-8")
        findings[t.lock] = run_pip_audit(path)
    plan = build_plan(findings, locks, dt.datetime.now(dt.timezone.utc), http_get_json,
                      force=args.force)
    pathlib.Path(args.output).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    for k, items in plan.items():
        for i in items:
            print(f"[{k}] {i['infile']}: {i['name']} {i['current']} — {i['reason']}")
    return 0


def cmd_apply(args) -> int:
    plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8"))
    for item in plan.get(args.group, []):
        path = ROOT / item["infile"]
        path.write_text(edit_infile(path.read_text(encoding="utf-8"), item["name"],
                                    item["version"], item["advisories"]), encoding="utf-8")
        print(f"pin {item['name']}=={item['version']} in {item['infile']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan")
    pp.add_argument("--output", required=True)
    pp.add_argument("--force", action="store_true", help="salta l'età minima (mai la provenienza)")
    pa = sub.add_parser("apply")
    pa.add_argument("--plan", required=True)
    pa.add_argument("--group", choices=["auto", "manual"], required=True)
    args = p.parse_args(argv)
    return cmd_plan(args) if args.cmd == "plan" else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
