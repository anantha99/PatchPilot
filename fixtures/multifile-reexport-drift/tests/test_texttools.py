import texttools
import texttools.slugs

from texttools import slugify
from texttools.slugs import slugify as direct_slugify


def test_public_slugify_reexports_canonical_function():
    assert texttools.slugify is texttools.slugs.slugify


def test_public_slugify_uses_hyphens():
    assert slugify("Ada Lovelace") == "ada-lovelace"


def test_direct_slugify_uses_same_contract():
    assert direct_slugify("Grace Hopper") == "grace-hopper"
