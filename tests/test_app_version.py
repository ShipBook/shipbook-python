import pytest

from shipbook.shipbook import _detect_app_version


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder with the working directory two levels inside it."""
    cwd = tmp_path / "project" / "src" / "app"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    return tmp_path / "project"


def test_the_version_comes_from_the_nearest_pyproject(project):
    (project / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\n\n'
        '[project]\nname = "orders"\nversion = "3.4.5"  # the release\n\n'
        '[tool.other]\nversion = "9.9.9"\n'
    )
    assert _detect_app_version() == "3.4.5"


def test_a_poetry_project_is_read_too(project):
    (project / "pyproject.toml").write_text("[tool.poetry]\nname = 'orders'\nversion = '1.2.0'\n")
    assert _detect_app_version() == "1.2.0"


def test_the_nearest_pyproject_decides_even_without_a_version(project):
    (project.parent / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    (project / "pyproject.toml").write_text('[project]\nname = "orders"\ndynamic = ["version"]\n')
    assert _detect_app_version() is None


def test_no_pyproject_means_no_version(project):
    assert _detect_app_version() is None
