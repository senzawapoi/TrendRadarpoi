"""Both supported installation manifests must express the same runtime contract."""

from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name

try:
    import tomllib
except ImportError:
    from pip._vendor import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


def contract(value):
    requirement = Requirement(value)
    return (
        canonicalize_name(requirement.name),
        tuple(sorted(requirement.extras)),
        tuple(sorted(str(spec) for spec in requirement.specifier)),
        str(requirement.marker) if requirement.marker else "",
        requirement.url,
    )


def test_runtime_dependency_manifests_match():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [
        line.split("#", 1)[0].strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    declared = metadata["project"]["dependencies"]
    assert {contract(value) for value in requirements} == {contract(value) for value in declared}
    assert len(requirements) == len({contract(value)[0] for value in requirements})
    assert len(declared) == len({contract(value)[0] for value in declared})
