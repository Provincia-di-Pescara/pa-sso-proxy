import os
from app.models import SpidCert

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")


def write_spid_cert(cert: SpidCert) -> None:
    """Write SPID SP certificate and private key PEM files to SATOSA conf dir."""
    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)
    with open(os.path.join(conf_dir, "spid_sp_cert.pem"), "w") as f:
        f.write(cert.certificate_pem)
    key_path = os.path.join(conf_dir, "spid_sp_key.pem")
    with open(key_path, "w") as f:
        f.write(cert.private_key_pem)
    os.chmod(key_path, 0o600)
