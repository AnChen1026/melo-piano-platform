import pytest

from scripts.ops.common import OpsError
from scripts.ops.database_refs import file_columns


def test_reference_contract_preserves_legacy_and_adds_cloud_score_sheet():
    legacy = file_columns("016_storage_cleanup")
    merged = file_columns("017_merge_storage_audio")
    sheet = ("practice_feedbacks", "score_sheet_path")
    assert sheet not in legacy
    assert sheet in merged
    assert set(legacy) < set(merged)


def test_reference_contract_matches_all_application_file_fields():
    from backend.services.storage_files import FILE_FIELDS

    assert set(file_columns("017_merge_storage_audio")) == {
        (model.__tablename__, field) for model, field in FILE_FIELDS
    }


def test_unknown_schema_is_rejected_instead_of_omitting_new_references():
    with pytest.raises(OpsError, match="unsupported_application_schema_revision"):
        file_columns("018_unknown")


@pytest.mark.parametrize(
    "revision",
    [
        "017_merge_storage_audio",
        "018_merge_availability_storage",
        "019_weekly_schedule",
        "020_course_embeddings",
        "021_assignment_quiz",
        "022_quiz_generation_jobs",
        "023_course_delivery_mode",
    ],
)
def test_later_revisions_keep_same_file_reference_contract(revision):
    from backend.services.storage_files import FILE_FIELDS

    assert set(file_columns(revision)) == {
        (model.__tablename__, field) for model, field in FILE_FIELDS
    }
