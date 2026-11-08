"""作業 API：老師發作業（可附參考 MIDI 與教材，或用 AI 從教材出題）、學生看作業、下載檔案、錄音繳交、題庫作答。"""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.storage import file_response
from backend.dependencies.common import require_roles
from backend.dependencies.teacher import get_current_teacher
from backend.models.teacher import TeacherDB
from backend.models.user import User
from backend.repositories.student import StudentRepository
from backend.schemas.student import (
    AssignmentResponse,
    FeedbackResponse,
    QuizAttemptIn,
    QuizAttemptResponse,
    QuizJobResponse,
    RecordingResponse,
    StudentQuizQuestionResponse,
    TeacherQuizQuestionResponse,
)
from backend.services import quiz_jobs
from backend.services.ai_quiz import MAX_SOURCE_BYTES, clean_question
from backend.services.assignment import (
    MAX_MATERIAL_BYTES,
    create_assignment,
    delete_assignment,
    list_student_assignments,
    list_teacher_assignments,
    material_for_student,
    material_for_teacher,
    own_assignment,
    quiz_attempt_rows,
    quiz_questions,
    student_assignment,
    submit_quiz_attempt,
)
from backend.services.course import MAX_MIDI_BYTES
from backend.services.practice import run_recording_analysis
from backend.services.student import MAX_RECORDING_BYTES, StudentBusinessError, save_recording

router = APIRouter(tags=["作業"])


def _raise(error: StudentBusinessError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _row(rows: list[dict], assignment_id: uuid.UUID) -> dict:
    return next(row for row in rows if row["id"] == assignment_id)


# ---------- 老師


@router.get("/teacher/assignments", response_model=list[AssignmentResponse])
def api_teacher_assignments(
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    return list_teacher_assignments(db, teacher.user_id)


@router.post("/teacher/assignments", response_model=AssignmentResponse, status_code=201)
def api_create_assignment(
    course_id: uuid.UUID = Form(...),
    student_id: uuid.UUID = Form(...),
    title: str = Form(...),
    kind: str = Form("performance"),
    description: str | None = Form(None),
    due_at: datetime | None = Form(None),
    midi: UploadFile | None = File(None),
    practice_bpm: int | None = Form(None),
    materials: list[UploadFile] | None = File(None),
    questions: str | None = Form(None),
    quiz_job_id: uuid.UUID | None = Form(None),
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    """multipart：midi 是參考曲（演奏作業才有），materials 可以放多個教材檔（樂譜、講義、示範音檔）。
    題庫作業的 questions 是 JSON 字串：AI 出題（/teacher/quiz/jobs）完成後老師審查、改過答案的題目陣列；
    帶 quiz_job_id 會把那次出題標成已發出，並留下老師最後的版本。"""
    try:
        question_list = json.loads(questions) if questions else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="題目資料格式不正確。")
    if question_list is not None and not isinstance(question_list, list):
        raise HTTPException(status_code=400, detail="題目資料格式不正確。")
    midi_file = (midi.filename or "reference.mid", midi.file.read(MAX_MIDI_BYTES + 1)) if midi and midi.filename else None
    files = [
        (item.filename or "material", item.content_type, item.file.read(MAX_MATERIAL_BYTES + 1))
        for item in materials or []
        if item.filename
    ]
    try:
        if quiz_job_id is not None:
            quiz_jobs.check_publishable(db, teacher.user_id, quiz_job_id)
        assignment = create_assignment(
            db,
            teacher.user_id,
            course_id,
            student_id,
            kind,
            title,
            description,
            due_at,
            midi_file,
            files,
            practice_bpm,
            questions=question_list,
        )
        if quiz_job_id is not None:
            final = [clean_question(item) for item in question_list or []]
            quiz_jobs.mark_published(db, teacher.user_id, quiz_job_id, assignment.id, [item for item in final if item])
    except StudentBusinessError as error:
        _raise(error)
    return _row(list_teacher_assignments(db, teacher.user_id), assignment.id)


@router.delete("/teacher/assignments/{assignment_id}", status_code=204)
def api_delete_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        delete_assignment(db, teacher.user_id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)


@router.get("/teacher/assignments/{assignment_id}/midi")
def api_teacher_assignment_midi(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        assignment = own_assignment(db, teacher.user_id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    if not assignment.midi_path:
        raise HTTPException(status_code=404, detail="這份作業沒有參考 MIDI。")
    return file_response(assignment.midi_path, media_type="audio/midi", filename=assignment.midi_filename)


@router.get("/teacher/assignment-materials/{material_id}")
def api_teacher_material(
    material_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        material = material_for_teacher(db, teacher.user_id, material_id)
    except StudentBusinessError as error:
        _raise(error)
    return file_response(material.file_path, media_type=material.content_type, filename=material.filename)


@router.post("/teacher/quiz/jobs", response_model=QuizJobResponse, status_code=202)
def api_create_quiz_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    count: int = Form(10),
    types: str = Form("single"),
    difficulty: str = Form("mixed"),
    title: str | None = Form(None),
    course_id: uuid.UUID | None = Form(None),
    student_id: uuid.UUID | None = Form(None),
    due_at: datetime | None = Form(None),
    use_ocr: bool = Form(False),
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    """題庫作業上傳：讀老師的教材（PDF／TXT），在背景請 AI 出題，馬上回應。
    types 用逗號分隔：single,multiple,truefalse；difficulty 是 easy／medium／hard／mixed。
    作業名稱與指派對象可以先帶著，審查完直接發作業。use_ocr 時辨識 PDF 裡的圖片文字。進度用 GET /teacher/quiz/jobs 看。"""
    data = file.file.read(MAX_SOURCE_BYTES + 1)
    try:
        job = quiz_jobs.create_job(
            db,
            teacher.user_id,
            file.filename or "",
            data,
            count,
            [item.strip() for item in types.split(",") if item.strip()],
            difficulty,
            title=title,
            course_id=course_id,
            student_id=student_id,
            due_at=due_at,
            use_ocr=use_ocr,
        )
    except StudentBusinessError as error:
        _raise(error)
    background_tasks.add_task(quiz_jobs.run_job, job.id)
    return job


@router.get("/teacher/quiz/jobs", response_model=list[QuizJobResponse])
def api_quiz_jobs(
    response: Response,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    """出題紀錄（不含題目，題目用單筆 API 拿）：排隊中、出題中、待審查、失敗。"""
    response.headers["Cache-Control"] = "no-store"
    return [QuizJobResponse.model_validate(job).model_copy(update={"questions": None}) for job in quiz_jobs.list_jobs(db, teacher.user_id)]


@router.get("/teacher/quiz/jobs/{job_id}", response_model=QuizJobResponse)
def api_quiz_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        return quiz_jobs.own_job(db, teacher.user_id, job_id)
    except StudentBusinessError as error:
        _raise(error)


@router.post("/teacher/quiz/jobs/{job_id}/retry", response_model=QuizJobResponse, status_code=202)
def api_retry_quiz_job(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    """「重新生成題目」：同一份教材與設定在背景再出一次。"""
    try:
        job = quiz_jobs.retry_job(db, teacher.user_id, job_id)
    except StudentBusinessError as error:
        _raise(error)
    background_tasks.add_task(quiz_jobs.run_job, job.id)
    return job


@router.delete("/teacher/quiz/jobs/{job_id}", status_code=204)
def api_discard_quiz_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        quiz_jobs.discard_job(db, teacher.user_id, job_id)
    except StudentBusinessError as error:
        _raise(error)


@router.get("/teacher/assignments/{assignment_id}/quiz", response_model=list[TeacherQuizQuestionResponse])
def api_teacher_quiz(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        assignment = own_assignment(db, teacher.user_id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    return quiz_questions(db, assignment.id)


@router.get("/teacher/assignments/{assignment_id}/quiz/attempts", response_model=list[QuizAttemptResponse])
def api_teacher_quiz_attempts(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    teacher: TeacherDB = Depends(get_current_teacher),
):
    try:
        assignment = own_assignment(db, teacher.user_id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    return quiz_attempt_rows(db, assignment.id)


# ---------- 學生

student_only = require_roles("student")


@router.get("/api/student/assignments", response_model=list[AssignmentResponse])
def api_student_assignments(
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    return list_student_assignments(db, student.id)


@router.get("/api/student/assignments/{assignment_id}/midi")
def api_student_assignment_midi(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    try:
        assignment = student_assignment(db, student.id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    if not assignment.midi_path:
        raise HTTPException(status_code=404, detail="這份作業沒有參考 MIDI。")
    return file_response(assignment.midi_path, media_type="audio/midi", filename=assignment.midi_filename)


@router.get("/api/student/assignment-materials/{material_id}")
def api_student_material(
    material_id: uuid.UUID,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    try:
        material = material_for_student(db, student.id, material_id)
    except StudentBusinessError as error:
        _raise(error)
    return file_response(material.file_path, media_type=material.content_type, filename=material.filename)


@router.get("/api/student/assignments/{assignment_id}/recordings", response_model=list[RecordingResponse])
def api_assignment_recordings(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    try:
        assignment = student_assignment(db, student.id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    recordings = [
        item for item in StudentRepository.list_recordings(db, student.id, assignment.course_id) if item.assignment_id == assignment.id
    ]
    return [_recording_response(db, item) for item in recordings]


@router.post("/api/student/assignments/{assignment_id}/recordings", response_model=RecordingResponse)
def api_submit_assignment(
    assignment_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    metronome_bpm: float | None = Form(None),
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    """繳交演奏作業：跟這份作業的參考 MIDI 比，評分在背景跑。錄音時有開節拍器就帶 metronome_bpm，節奏照它算。"""
    try:
        assignment = student_assignment(db, student.id, assignment_id)
        if assignment.kind != "performance":
            raise StudentBusinessError(400, "題庫作業不用錄音繳交。")
        recording = save_recording(
            db,
            student,
            assignment.course_id,
            audio.filename or "audio.webm",
            audio.file.read(MAX_RECORDING_BYTES + 1),
            assignment=assignment,
            metronome_bpm=metronome_bpm,
        )
    except StudentBusinessError as error:
        _raise(error)
    background_tasks.add_task(run_recording_analysis, recording.id)
    return _recording_response(db, recording)


def _recording_response(db: Session, recording) -> RecordingResponse:
    feedback = StudentRepository.get_feedback(db, recording.id)
    return RecordingResponse(
        id=recording.id,
        course_id=recording.course_id,
        assignment_id=recording.assignment_id,
        metronome_bpm=recording.metronome_bpm,
        status=recording.status,
        submitted_at=recording.submitted_at,
        feedback=FeedbackResponse.model_validate(feedback) if feedback else None,
    )


@router.get("/api/student/assignments/{assignment_id}/quiz", response_model=list[StudentQuizQuestionResponse])
def api_student_quiz(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    """題庫作業的題目：不含答案與解析，有提示。"""
    try:
        assignment = student_assignment(db, student.id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    return quiz_questions(db, assignment.id)


@router.get("/api/student/assignments/{assignment_id}/quiz/attempts", response_model=list[QuizAttemptResponse])
def api_student_quiz_attempts(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    try:
        assignment = student_assignment(db, student.id, assignment_id)
    except StudentBusinessError as error:
        _raise(error)
    return quiz_attempt_rows(db, assignment.id)


@router.post("/api/student/assignments/{assignment_id}/quiz/attempts", response_model=QuizAttemptResponse, status_code=201)
def api_submit_quiz(
    assignment_id: uuid.UUID,
    payload: QuizAttemptIn,
    db: Session = Depends(get_db),
    student: User = Depends(student_only),
):
    """交一次題庫作答，回傳這次答錯的題目、正確答案與解析。"""
    answers: dict[uuid.UUID, list[int]] = {}
    for item in payload.answers:
        answers[item.question_id] = item.selected
    try:
        attempt = submit_quiz_attempt(db, student.id, assignment_id, answers)
    except StudentBusinessError as error:
        _raise(error)
    return next(row for row in quiz_attempt_rows(db, assignment_id) if row["id"] == attempt.id)
