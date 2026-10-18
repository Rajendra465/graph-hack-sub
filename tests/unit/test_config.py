"""Settings from the environment: a public deployment's host name is read, lowercased and checked."""

from __future__ import annotations

import pytest

from codebook import config


def test_there_is_no_public_host_by_default():
    assert config.load({}).public_host == ""


def test_the_public_host_is_read_and_lowercased():
    settings = config.load({"CODEBOOK_PUBLIC_HOST": "Sarpal465-Codebook.hf.space"})
    assert settings.public_host == "sarpal465-codebook.hf.space"


@pytest.mark.parametrize("raw", ["https://demo.hf.space", "demo.hf.space/path", "bad host"])
def test_a_public_host_that_is_not_a_host_name_is_refused(raw):
    with pytest.raises(config.ConfigError):
        config.load({"CODEBOOK_PUBLIC_HOST": raw})
