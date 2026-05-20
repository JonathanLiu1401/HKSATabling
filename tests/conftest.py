"""Shared pytest fixtures for the HKSA scheduler test suite.

Adds the repository root to sys.path so test files can `import scheduler_core` and
`import app` directly, and exposes builders for common test objects.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

import scheduler_core as core  # noqa: E402


@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def small_sample_csv_path(repo_root):
    return repo_root / "small_sample.csv"


@pytest.fixture
def med_sample_csv_path(repo_root):
    return repo_root / "med_sample.csv"


@pytest.fixture
def big_sample_csv_path(repo_root):
    return repo_root / "big_sample.csv"


@pytest.fixture
def availability_csv_path(repo_root):
    return repo_root / "Availability.csv"


def make_member(
    name,
    gender="Male",
    availability=None,
    avoid_opening=False,
    avoid_closing=False,
    preferred_days=None,
    time_overrides=None,
):
    """Build a Member with sensible defaults.

    By default the member is available for every slot on every day, so individual
    tests only need to override the fields they care about.
    """
    if availability is None:
        availability = {d: list(core.TIME_SLOTS.values()) for d in core.ALL_DAYS}
    return core.Member(
        name=name,
        gender=gender,
        availability=availability,
        avoid_opening=avoid_opening,
        avoid_closing=avoid_closing,
        preferred_days=preferred_days or [],
        time_overrides=time_overrides or {},
    )


@pytest.fixture
def member_builder():
    return make_member


@pytest.fixture
def full_pool():
    """16 unconstrained Male members — enough to fill a full Mon-Fri × 4-slot grid
    (20 slots × 2 people = 40 assignments, but with 1-shift-per-week we need >= 40
    members for a complete schedule). Use this fixture's expansion for tests that
    actually need a full schedule."""
    return [make_member(f"Member_{i:02d}") for i in range(16)]


@pytest.fixture
def fillable_pool():
    """40 Male members — enough to fully cover a Mon-Fri × 4-slot grid."""
    return [make_member(f"Member_{i:02d}") for i in range(40)]


@pytest.fixture
def mixed_pool():
    """40 members, mix of genders. Indices 0-19 Male, 20-39 Female."""
    pool = []
    for i in range(20):
        pool.append(make_member(f"M_{i:02d}", gender="Male"))
    for i in range(20):
        pool.append(make_member(f"F_{i:02d}", gender="Female"))
    return pool


import io  # noqa: E402


class FakeUpload:
    """Stand-in for a Streamlit UploadedFile. parse_file calls pd.read_csv/read_excel
    on the object directly, and pandas only needs a file-like buffer + a .name with
    the right extension."""

    def __init__(self, data, name):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, attr):
        # Delegate buffer methods (read, seek, tell, getvalue, etc.) to the BytesIO.
        return getattr(self._buf, attr)


@pytest.fixture
def fake_file_factory():
    """Returns a callable that wraps a path in a FakeUpload."""
    def _make(path, name=None):
        path = Path(path)
        with open(path, "rb") as f:
            data = f.read()
        return FakeUpload(data, name=name or path.name)
    return _make


@pytest.fixture
def fake_csv_factory():
    """Returns a callable that builds a FakeUpload from raw CSV text."""
    def _make(csv_text, name="test.csv"):
        return FakeUpload(csv_text.encode("utf-8"), name=name)
    return _make
