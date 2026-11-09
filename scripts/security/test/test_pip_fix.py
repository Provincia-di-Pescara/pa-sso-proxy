"""Test di scripts/security/pip_fix.py su copie FISSE dei file (fixtures/).

Mai i file vivi del repo: dependabot e l'autofix li modificano e i test
fallirebbero proprio sulle loro PR. Nessuna rete: PyPI e OSV sono simulati.
Esecuzione: python -m unittest discover -s scripts/security/test -v
"""
import datetime as dt
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pip_fix  # noqa: E402

FIX = HERE / "fixtures"
NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)


def iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


class FakeNet:
    """PyPI/OSV simulati: releases[(name, version)] = (ore fa, repository o None)."""

    def __init__(self, releases, severities):
        self.releases = releases
        self.severities = severities
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url.startswith("https://api.osv.dev/v1/vulns/"):
            vid = url.rsplit("/", 1)[1]
            sev = self.severities.get(vid)
            return {"id": vid, "database_specific": {"severity": sev}} if sev else None
        if url.startswith("https://pypi.org/pypi/"):
            _, _, _, _, name, version, _ = url.split("/")
            rel = self.releases.get((name, version))
            if rel is None:
                return None
            return {"urls": [{"filename": f"{name}-{version}-py3-none-any.whl",
                              "upload_time_iso_8601": iso(rel[0])}]}
        if url.startswith("https://pypi.org/integrity/"):
            parts = url.split("/")
            name, version = parts[4], parts[5]
            rel = self.releases.get((name, version))
            if not rel or not rel[1]:
                return None
            return {"attestation_bundles": [{"publisher": {"kind": "GitHub",
                                                           "repository": rel[1]}}]}
        raise AssertionError(f"URL inattesa: {url}")


class ParseTests(unittest.TestCase):
    def test_parse_lock_hash_format_and_extras(self):
        pins = pip_fix.parse_lock((FIX / "requirements.txt.fixture").read_text())
        self.assertEqual(pins["starlette"], "0.50.0")
        self.assertEqual(pins["uvicorn"], "0.54.0")
        self.assertNotIn("--hash", "".join(pins))

    def test_parse_audit(self):
        found = pip_fix.parse_audit(json.loads((FIX / "pip-audit.json").read_text()))
        self.assertEqual({f["name"] for f in found}, {"starlette", "cryptography"})

    def test_version_key(self):
        k = pip_fix.version_key
        self.assertLess(k("0.50.0"), k("0.50.2"))
        self.assertLess(k("0.50.2"), k("0.51.0"))
        self.assertLess(k("1.0rc1"), k("1.0"))
        self.assertLess(k("1.0"), k("1.0.post1"))
        self.assertLess(k("2.9"), k("2.10"))


class ChooseVersionTests(unittest.TestCase):
    def net(self, new_age=100, new_repo="encode/starlette", cur_repo="encode/starlette"):
        return FakeNet({("starlette", "0.50.0"): (2000, cur_repo),
                        ("starlette", "0.50.2"): (new_age, new_repo),
                        ("starlette", "0.51.0"): (10, new_repo)}, {})

    def test_lowest_fixing_version(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.51.0", "0.50.2"], NOW, self.net())
        self.assertEqual((c.status, c.version), ("ok", "0.50.2"))

    def test_too_young_is_pending(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW, self.net(new_age=20))
        self.assertEqual((c.status, c.version), ("pending", None))

    def test_force_skips_age_only(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW,
                                   self.net(new_age=20), force=True)
        self.assertEqual(c.status, "ok")
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW,
                                   self.net(new_age=20, new_repo="evil/fork"), force=True)
        self.assertEqual(c.status, "unfixable")

    def test_different_repository_is_refused(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW,
                                   self.net(new_repo="someone/else"))
        self.assertEqual(c.status, "unfixable")
        self.assertIn("diversa", c.reason)

    def test_missing_provenance_is_refused(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW, self.net(new_repo=None))
        self.assertEqual(c.status, "unfixable")
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.50.2"], NOW, self.net(cur_repo=None))
        self.assertEqual(c.status, "unfixable")

    def test_no_newer_fix(self):
        c = pip_fix.choose_version("starlette", "0.50.0", ["0.49.9"], NOW, self.net())
        self.assertEqual(c.status, "unfixable")


class EditInfileTests(unittest.TestCase):
    def setUp(self):
        self.text = (FIX / "requirements.in").read_text()

    def test_direct_dependency_line_is_updated_keeping_extras(self):
        out = pip_fix.edit_infile(self.text, "uvicorn", "0.54.1", ["GHSA-x"])
        self.assertIn("uvicorn[standard]==0.54.1  # security-autofix: GHSA-x\n", out)
        self.assertNotIn("uvicorn[standard]==0.54.0", out)
        self.assertEqual(out.count("fastapi==0.158.1"), 1)

    def test_transitive_dependency_is_appended_with_removal_condition(self):
        out = pip_fix.edit_infile(self.text, "starlette", "0.50.2", ["GHSA-aaaa-bbbb-cccc"])
        self.assertTrue(out.startswith(self.text))
        self.assertIn("starlette==0.50.2\n", out)
        self.assertIn("Rimuovere quando", out)

    def test_name_normalization(self):
        out = pip_fix.edit_infile("Foo_Bar==1.0\n", "foo-bar", "1.1", ["X"])
        self.assertEqual(out, "Foo_Bar==1.1  # security-autofix: X\n")


class BuildPlanTests(unittest.TestCase):
    def test_groups_and_parent_dedup(self):
        findings_runtime = pip_fix.parse_audit(json.loads((FIX / "pip-audit.json").read_text()))
        findings = {"config-api/requirements.txt": findings_runtime,
                    # starlette compare anche nel lock dev: si corregge solo nel runtime
                    "config-api/requirements-dev.txt": [f for f in findings_runtime
                                                        if f["name"] == "starlette"]}
        locks = {"config-api/requirements.txt": (FIX / "requirements.txt.fixture").read_text(),
                 "config-api/requirements-dev.txt": (FIX / "requirements-dev.txt.fixture").read_text()}
        net = FakeNet({("starlette", "0.50.0"): (2000, "encode/starlette"),
                       ("starlette", "0.50.2"): (100, "encode/starlette"),
                       ("cryptography", "50.0.2"): (2000, "pyca/cryptography"),
                       ("cryptography", "50.0.3"): (100, "pyca/cryptography")},
                      {"GHSA-aaaa-bbbb-cccc": "HIGH", "GHSA-cryp-tooo-0001": "CRITICAL"})
        plan = pip_fix.build_plan(findings, locks, NOW, net)
        self.assertEqual([i["name"] for i in plan["auto"]], ["starlette"])
        self.assertEqual(plan["auto"][0]["infile"], "config-api/requirements.in")
        self.assertEqual([i["name"] for i in plan["manual"]], ["cryptography"])
        self.assertEqual(plan["pending"] + plan["unfixable"], [])

    def test_low_severity_is_ignored(self):
        findings = {"config-api/requirements.txt": [
            {"name": "starlette", "version": "0.50.0", "id": "GHSA-low",
             "aliases": [], "fix_versions": ["0.50.2"]}]}
        net = FakeNet({}, {"GHSA-low": "LOW"})
        plan = pip_fix.build_plan(findings, {}, NOW, net)
        self.assertEqual(sum(len(v) for v in plan.values()), 0)


if __name__ == "__main__":
    unittest.main()
