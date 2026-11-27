"""Mappatura attributi IT-Wallet (profilo `openid4vp`) in internal_attributes.yaml.

Solo nel container satosa: il file vive in /satosa_proxy/internal_attributes.yaml.
"""

import pytest
import yaml

from satosa.attribute_mapping import AttributeMapper

YAML_PATH = "/satosa_proxy/internal_attributes.yaml"


@pytest.fixture(scope="module")
def internal_attributes():
    with open(YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_openid4vp_mappings(internal_attributes):
    attrs = internal_attributes["attributes"]
    assert attrs["fiscalnumber"]["openid4vp"] == ["tax_id_code"]
    assert attrs["birthdate"]["openid4vp"] == ["birthdate"]
    assert attrs["dateOfBirth"]["openid4vp"] == ["birthdate"]
    assert attrs["placeOfBirth"]["openid4vp"] == ["place_of_birth"]


@pytest.mark.xfail(strict=True, reason="appiattimento nel backend IT-Wallet, Task 4")
def test_place_of_birth_flattened(internal_attributes):
    mapper = AttributeMapper(internal_attributes)
    internal = mapper.to_internal("openid4vp", {"place_of_birth": {"locality": "Roma"}})
    out = mapper.from_internal("openid", internal)
    assert out["place_of_birth"] == "Roma"
