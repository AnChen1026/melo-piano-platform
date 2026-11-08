"""Application file-reference contract for supported schema revisions; independent of web code.

Update this list when deploying a new file-bearing model. All bucket objects
are backed up regardless; this contract adds snapshot-reference verification.
"""

FILE_COLUMNS = [
    ("courses", "reference_midi_path"),
    ("courses", "image_path"),
    ("reference_midis", "storage_key"),
    ("practice_recordings", "file_path"),
    ("practice_recordings", "reference_midi_path"),
    ("assignments", "midi_path"),
    ("assignment_materials", "file_path"),
    ("learning_materials", "file_path"),
    ("teacher_profiles", "photo_path"),
    ("teacher_applications", "proof_file_path"),
]


def file_columns(revision):
    from scripts.ops.common import OpsError

    if revision == "016_storage_cleanup":
        return list(FILE_COLUMNS)
    if revision in {
        "017_merge_storage_audio",
        "018_merge_availability_storage",
        "019_weekly_schedule",
        "020_course_embeddings",
        "021_assignment_quiz",
        "022_quiz_generation_jobs",
        "023_course_delivery_mode",
    }:
        return [*FILE_COLUMNS, ("practice_feedbacks", "score_sheet_path")]
    raise OpsError("unsupported_application_schema_revision")
