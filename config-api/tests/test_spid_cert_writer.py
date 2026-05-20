import pytest
from datetime import datetime, timezone
from app.models import SpidCert
from app.spid_cert_writer import write_spid_cert


def test_write_spid_cert_creates_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----\n",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----\n",
        not_valid_after=datetime(2030, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=test",
    )
    write_spid_cert(cert)
    assert (tmp_path / "spid_sp_cert.pem").read_text() == cert.certificate_pem
    assert (tmp_path / "spid_sp_key.pem").read_text() == cert.private_key_pem


def test_write_spid_cert_creates_dir(tmp_path, monkeypatch):
    target = tmp_path / "deep" / "conf"
    monkeypatch.setenv("SATOSA_CONF_DIR", str(target))
    cert = SpidCert(
        certificate_pem="CERT\n",
        private_key_pem="KEY\n",
        not_valid_after=datetime(2030, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=test",
    )
    write_spid_cert(cert)
    assert (target / "spid_sp_cert.pem").exists()
    assert (target / "spid_sp_key.pem").exists()
