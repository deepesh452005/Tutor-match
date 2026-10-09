import base64
import secrets
from datetime import date, time
from typing import List, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import hash_password, make_token, verify_password
from database import (
    area_exists,
    bump_reset_attempts,
    create_contact_request,
    create_password_reset,
    create_session,
    create_trial_booking,
    create_tutoring_request,
    create_tutor_review,
    create_user,
    delete_resolved_student_request,
    delete_resolved_tutor_request,
    delete_expired_sessions,
    delete_expired_scheduled_requests,
    delete_resets_for_user,
    delete_session,
    delete_sessions_for_user,
    get_active_reset,
    get_all_areas,
    get_all_tutors_for_search,
    get_incoming_requests,
    get_incoming_trial_bookings,
    get_incoming_tutoring_requests,
    get_password_hash,
    get_public_tutor_profile,
    get_request_between,
    get_request_for_response,
    get_request_statuses_for_student,
    get_requests_by_student,
    get_tutor_accepting,
    get_tutor_profile,
    get_trial_booking_for_response,
    get_trial_bookings_by_student,
    get_tutoring_request_for_response,
    get_tutoring_requests_by_student,
    get_user_by_email,
    get_user_by_token,
    init_db,
    recent_reset_exists,
    save_tutor_profile,
    seed_areas,
    set_contact_request_visibility,
    set_trial_contact_visibility,
    set_tutoring_contact_visibility,
    set_tutor_accepting,
    update_password,
    update_request_status,
    update_trial_booking_status,
    update_tutoring_request,
    update_tutoring_request_status,
    update_user_profile,
)
from mailer import EMAIL_ENABLED, send_reset_code
from matching import find_matching_tutors

app = FastAPI(title="Tutor Match")
bearer = HTTPBearer()  # makes the "Authorize" button show up in /docs

# Serve everything inside the "static" folder
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def startup():
    init_db()
    seed_areas()
    delete_expired_sessions()
    delete_expired_scheduled_requests()


# ---------- what the forms must contain ----------

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    role: Literal["student", "tutor"]
    area_id: int


class LoginRequest(BaseModel):
    email: str
    password: str


class EditProfileBody(BaseModel):
    name: str
    area_id: int
    avatar_action: Literal["keep", "set", "remove"] = "keep"
    avatar: Optional[str] = None   # only used when avatar_action is "set"


class TutorProfileRequest(BaseModel):
    qualification: str
    bio: str = ""
    subjects: List[str]
    min_class: int
    max_class: int
    available_from: int  # hour 0-23, e.g. 16 = 4 PM
    available_to: int    # hour 0-23, e.g. 20 = 8 PM
    max_hours_per_day: Optional[int] = None
    phone: str


class AvailabilityBody(BaseModel):
    accepting: bool


class SearchRequest(BaseModel):
    subject: Optional[str] = None
    class_level: Optional[int] = None
    from_hour: Optional[int] = None  # e.g. 17 = 5 PM
    to_hour: Optional[int] = None    # e.g. 18 = 6 PM
    radius_km: Optional[float] = None


class ContactRequestBody(BaseModel):
    tutor_id: int
    message: str = ""


class TrialBookingBody(BaseModel):
    tutor_id: int
    child_name: str
    phone: str
    class_level: int
    subject: str
    preferred_date: date
    preferred_time: time
    message: str = ""


class TutoringRequestBody(BaseModel):
    tutor_id: int
    child_name: str
    phone: str
    class_level: int
    subjects: List[str]
    weekdays: List[str]
    start_date: date
    end_date: date
    preferred_from: time
    preferred_to: time
    message: str = ""


class TutorReviewBody(BaseModel):
    rating: int
    review: str


class RespondBody(BaseModel):
    action: Literal["accept", "decline"]
    reason: str = ""


class ContactVisibilityBody(BaseModel):
    visible: bool


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    email: str
    code: str
    new_password: str


# ---------- small helpers ----------

def clean_phone(raw: str):
    """Returns a clean 10-digit Indian mobile number, or None if it isn't valid."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return digits


def clean_avatar(data_url):
    """Accepts only a small, real JPEG sent as a data URL. Returns it, or None if it's not OK.
    (The website shrinks every photo to a square JPEG before sending.)"""
    prefix = "data:image/jpeg;base64,"
    if not data_url or not data_url.startswith(prefix) or len(data_url) > 80_000:
        return None
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except Exception:
        return None
    if not raw.startswith(b"\xff\xd8\xff"):  # every real JPEG starts with these bytes
        return None
    return data_url


# ---------- wristband checker ----------

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    user = get_user_by_token(creds.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired login. Please log in again.")
    return user


# ---------- the website itself ----------

@app.get("/", include_in_schema=False)
def home():
    return FileResponse("static/index.html")


# ---------- basic endpoints ----------

@app.get("/areas")
def list_areas():
    return get_all_areas()


# ---------- signup / login / logout ----------

@app.post("/signup")
def signup(data: SignupRequest):
    email = data.email.strip().lower()
    name = data.name.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email.")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if not area_exists(data.area_id):
        raise HTTPException(status_code=400, detail="Please choose a valid area.")
    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="This email is already registered.")

    user_id = create_user(name, email, hash_password(data.password), data.role, data.area_id)

    token = make_token()
    create_session(token, user_id)
    return {"message": "Account created!", "token": token, "role": data.role}


@app.post("/login")
def login(data: LoginRequest):
    email = data.email.strip().lower()
    user = get_user_by_email(email)

    # Same message for both cases, so strangers can't guess which emails exist
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    delete_expired_sessions()
    token = make_token()
    create_session(token, user["id"])
    return {"message": "Logged in!", "token": token, "role": user["role"]}


@app.post("/logout")
def logout(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    # Deactivate the wristband on the server too (not just forget it in the browser)
    delete_session(creds.credentials)
    return {"message": "Logged out."}


@app.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


# ---------- edit my profile (name, area, photo) ----------

@app.put("/me/profile")
def edit_my_profile(data: EditProfileBody, user: dict = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="Name is too long (max 60 characters).")
    if not area_exists(data.area_id):
        raise HTTPException(status_code=400, detail="Please choose a valid area.")

    avatar = None
    if data.avatar_action == "set":
        avatar = clean_avatar(data.avatar)
        if avatar is None:
            raise HTTPException(status_code=400, detail="That photo couldn't be used. Please try a different JPG or PNG.")

    update_user_profile(user["id"], name, data.area_id, data.avatar_action, avatar)
    return {"message": "Profile updated!"}


# ---------- change password (kept in the server for later, the website doesn't show it now) ----------

@app.post("/change-password")
def change_password(data: ChangePasswordBody, user: dict = Depends(get_current_user)):
    # NOTE: wrong-password errors use 400, not 401, because the website treats a 401
    # as "your login expired" and would throw you out.
    stored = get_password_hash(user["id"])
    if not stored or not verify_password(data.current_password, stored):
        raise HTTPException(status_code=400, detail="Your current password is wrong.")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")
    if data.new_password == data.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")

    update_password(user["id"], hash_password(data.new_password))

    # Change the locks: every old wristband (all devices) stops working...
    delete_sessions_for_user(user["id"])
    # ...and this device gets a fresh one so you stay logged in
    token = make_token()
    create_session(token, user["id"])
    return {"message": "Password changed!", "token": token}


# ---------- forgot password (you DON'T know the old one) ----------

RESET_MESSAGE = "If that email is registered, a 6-digit code has been sent. It works for 15 minutes."


def issue_reset_code(email: str):
    """Runs in the background, so the reply is instant and looks identical
    whether or not the email exists."""
    user = get_user_by_email(email)
    if not user or recent_reset_exists(user["id"]):
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    create_password_reset(user["id"], hash_password(code))  # we store only the shredded code
    send_reset_code(email, code)


@app.post("/forgot-password")
def forgot_password(data: ForgotPasswordBody, background: BackgroundTasks):
    background.add_task(issue_reset_code, data.email.strip().lower())
    return {"message": RESET_MESSAGE, "email_enabled": EMAIL_ENABLED}


@app.post("/reset-password")
def reset_password(data: ResetPasswordBody):
    def wrong_code():
        return HTTPException(
            status_code=400,
            detail="That code is wrong or has expired. Please request a new one.",
        )

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")

    user = get_user_by_email(data.email.strip().lower())
    if not user:
        raise wrong_code()

    reset = get_active_reset(user["id"])
    if not reset:
        raise wrong_code()

    if not verify_password(data.code.strip(), reset["code_hash"]):
        bump_reset_attempts(reset["id"])  # 5 wrong tries and the code dies
        raise wrong_code()

    update_password(user["id"], hash_password(data.new_password))
    delete_resets_for_user(user["id"])       # the code can only be used once
    delete_sessions_for_user(user["id"])     # log out everywhere, just to be safe
    return {"message": "Password changed! You can log in now."}


# ---------- tutor profile (visiting card) ----------

@app.put("/tutor/profile")
def update_tutor_profile(data: TutorProfileRequest, user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors can have a tutor profile.")

    subjects = [s.strip() for s in data.subjects if s.strip()]
    phone = clean_phone(data.phone)

    if not data.qualification.strip():
        raise HTTPException(status_code=400, detail="Qualification is required.")
    if len(data.bio.strip()) > 600:
        raise HTTPException(status_code=400, detail="About me must be 600 characters or fewer.")
    if not subjects:
        raise HTTPException(status_code=400, detail="Add at least one subject.")
    if not (1 <= data.min_class <= data.max_class <= 12):
        raise HTTPException(status_code=400, detail="Classes must be between 1 and 12, and min can't be above max.")
    if not (0 <= data.available_from < data.available_to <= 23):
        raise HTTPException(status_code=400, detail="Timings must be hours 0-23, and 'from' must be before 'to'.")
    if data.max_hours_per_day is not None and data.max_hours_per_day < 1:
        raise HTTPException(status_code=400, detail="Max hours per day must be at least 1.")
    if phone is None:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number.")

    save_tutor_profile(
        user["id"], data.qualification.strip(), subjects,
        data.min_class, data.max_class,
        data.available_from, data.available_to, data.max_hours_per_day, phone,
        data.bio.strip(),
    )
    return {"message": "Tutor profile saved!"}


@app.get("/tutor/profile")
def read_tutor_profile(user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors have a tutor profile.")

    profile = get_tutor_profile(user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="No profile yet. Fill it in first.")
    return profile


@app.get("/tutors/{tutor_id}")
def tutor_overview(tutor_id: int, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can view tutor overviews.")
    profile = get_public_tutor_profile(tutor_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Tutor not found.")
    return profile


@app.post("/tutors/{tutor_id}/reviews")
def review_tutor(tutor_id: int, data: TutorReviewBody, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can review tutors.")
    if not 1 <= data.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5 stars.")
    review = data.review.strip()
    if not 10 <= len(review) <= 500:
        raise HTTPException(status_code=400, detail="Review must be between 10 and 500 characters.")

    profile = get_public_tutor_profile(tutor_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Tutor not found.")
    if not profile["can_review"]:
        raise HTTPException(status_code=403, detail="You can review a tutor after they accept your request.")
    if profile["existing_review"]:
        raise HTTPException(status_code=400, detail="You have already reviewed this tutor.")
    if create_tutor_review(user["id"], tutor_id, data.rating, review) is None:
        raise HTTPException(status_code=400, detail="You have already reviewed this tutor.")
    return {"message": "Your review was submitted."}


@app.put("/tutor/availability")
def set_availability(data: AvailabilityBody, user: dict = Depends(get_current_user)):
    """The OPEN / CLOSED sign. Only the tutor can flip their own."""
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors can change availability.")

    if not set_tutor_accepting(user["id"], data.accepting):
        raise HTTPException(status_code=404, detail="Save your tutor profile first.")

    if data.accepting:
        return {"message": "You're showing as Available again.", "accepting": True}
    return {"message": "You're now showing as Not available.", "accepting": False}


# ---------- the real search ----------

@app.post("/search")
def search_tutors(data: SearchRequest, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can search for tutors.")

    if data.class_level is not None and not (1 <= data.class_level <= 12):
        raise HTTPException(status_code=400, detail="Class must be between 1 and 12.")
    if (data.from_hour is None) != (data.to_hour is None):
        raise HTTPException(status_code=400, detail="Choose both a start and end time, or leave both as Any time.")
    if data.from_hour is not None and not (0 <= data.from_hour < data.to_hour <= 23):
        raise HTTPException(status_code=400, detail="Timings must be hours 0-23, and 'from' must be before 'to'.")
    if data.radius_km is not None and not (0 < data.radius_km <= 50):
        raise HTTPException(status_code=400, detail="Distance must be between 0 and 50 km.")

    search = {
        "subject": data.subject.strip() if data.subject else None,
        "class": data.class_level,
        "from_hour": data.from_hour,
        "to_hour": data.to_hour,
        "radius_km": data.radius_km,
        "lat": user["latitude"],   # student's saved area is the centre point
        "lon": user["longitude"],
    }

    all_tutors = get_all_tutors_for_search()
    matches = find_matching_tutors(search, all_tutors)
    statuses = get_request_statuses_for_student(user["id"])

    results = []
    for t in matches:
        status = statuses.get(t["tutor_id"])  # None, "pending", "accepted" or "declined"
        results.append({
            "tutor_id": t["tutor_id"],
            "name": t["name"],
            "avatar": t["avatar"],   # the profile photo shown on top of the tutor card
            "qualification": t["qualification"],
            "subjects": t["subjects"],
            "rating_average": t["rating_average"],
            "review_count": t["review_count"],
            "classes": f"{t['min_class']}-{t['max_class']}",
            "available": f"{t['available_from']}:00 - {t['available_to']}:00",
            "area": t["area_name"],
            "distance_km": t["distance_km"],
            "accepting": bool(t["is_accepting"]),   # False = tutor paused (shown as Not available)
            "request_status": status,
        })

    # Open shops first, closed ones after; nearest first inside each group
    results.sort(key=lambda r: (not r["accepting"], r["distance_km"]))

    return {
        "tutors_checked": len(all_tutors),
        "tutors_found": len(results),
        "tutors_available": sum(1 for r in results if r["accepting"]),
        "tutors": results,
    }


# ---------- contact requests (the doorbell) ----------

@app.post("/requests")
def send_request(data: ContactRequestBody, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can send contact requests.")

    message = data.message.strip()
    if len(message) > 300:
        raise HTTPException(status_code=400, detail="Message is too long (max 300 characters).")

    accepting = get_tutor_accepting(data.tutor_id)
    if accepting is None:
        raise HTTPException(status_code=404, detail="Tutor not found.")
    if not accepting:
        raise HTTPException(status_code=400, detail="This tutor isn't taking new students right now.")

    existing = get_request_between(user["id"], data.tutor_id)
    if existing:
        if existing["status"] == "pending":
            raise HTTPException(status_code=400, detail="You already sent a request to this tutor. Please wait for their reply.")
        if existing["status"] == "accepted":
            raise HTTPException(status_code=400, detail="This tutor already accepted. Check 'My requests' for the number.")
        raise HTTPException(status_code=400, detail="This tutor declined your earlier request.")

    request_id = create_contact_request(user["id"], data.tutor_id, message)
    if request_id is None:
        raise HTTPException(status_code=400, detail="You already sent a request to this tutor.")

    return {"message": "Request sent!", "status": "pending"}


@app.get("/requests/sent")
def my_sent_requests(user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students have sent requests.")
    return get_requests_by_student(user["id"])


def delete_request(request_type: str, request_id: int, user: dict):
    if user["role"] == "student":
        deleted = delete_resolved_student_request(request_type, request_id, user["id"])
    elif user["role"] == "tutor":
        deleted = delete_resolved_tutor_request(request_type, request_id, user["id"])
    else:
        deleted = False
        raise HTTPException(status_code=403, detail="Only request participants can delete requests.")
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail="Only the request's student or tutor can delete it, and only after it has been accepted or declined.",
        )
    return {"message": "Request deleted."}


def validated_decline_reason(data: RespondBody) -> str:
    reason = data.reason.strip()
    if data.action == "decline" and not reason:
        raise HTTPException(status_code=400, detail="Please provide a reason for declining.")
    if len(reason) > 300:
        raise HTTPException(status_code=400, detail="Decline reason must be 300 characters or fewer.")
    return reason if data.action == "decline" else ""


@app.delete("/requests/{request_id}")
def delete_contact_request(request_id: int, user: dict = Depends(get_current_user)):
    return delete_request("requests", request_id, user)


@app.get("/requests/incoming")
def my_incoming_requests(user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors have an inbox.")
    return get_incoming_requests(user["id"])


@app.post("/trials")
def request_trial(data: TrialBookingBody, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can request free trials.")
    child_name = data.child_name.strip()
    subject = data.subject.strip()
    message = data.message.strip()
    phone = clean_phone(data.phone)
    if not child_name or len(child_name) > 60:
        raise HTTPException(status_code=400, detail="Student name is required (max 60 characters).")
    if phone is None:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number.")
    if not 1 <= data.class_level <= 12:
        raise HTTPException(status_code=400, detail="Class must be between 1 and 12.")
    if len(message) > 300:
        raise HTTPException(status_code=400, detail="Message is too long (max 300 characters).")
    if data.preferred_date < date.today():
        raise HTTPException(status_code=400, detail="Choose today or a future date.")

    profile = get_public_tutor_profile(data.tutor_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Tutor not found.")
    if not profile["is_accepting"]:
        raise HTTPException(status_code=400, detail="This tutor isn't taking new students right now.")
    if not profile["min_class"] <= data.class_level <= profile["max_class"]:
        raise HTTPException(status_code=400, detail="This tutor doesn't teach that class.")
    if subject not in profile["subjects"]:
        raise HTTPException(status_code=400, detail="This tutor doesn't teach that subject.")
    if not profile["available_from"] <= data.preferred_time.hour < profile["available_to"]:
        raise HTTPException(status_code=400, detail="Choose a time within the tutor's listed availability.")

    booking_id = create_trial_booking(
        user["id"], data.tutor_id, child_name, phone, data.class_level, subject,
        data.preferred_date.isoformat(), data.preferred_time.strftime("%H:%M"), message,
    )
    if booking_id is None:
        raise HTTPException(
            status_code=400,
            detail="You already requested a free trial with this tutor for this subject. Choose another subject.",
        )
    return {"message": "Free-trial request sent. The tutor will confirm your time."}


@app.get("/trials/sent")
def my_trial_requests(user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students have trial requests.")
    return get_trial_bookings_by_student(user["id"])


@app.delete("/trials/{booking_id}")
def delete_trial_request(booking_id: int, user: dict = Depends(get_current_user)):
    return delete_request("trials", booking_id, user)


@app.get("/trials/incoming")
def my_incoming_trials(user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors have trial requests.")
    return get_incoming_trial_bookings(user["id"])


@app.post("/trials/{booking_id}/respond")
def respond_to_trial(booking_id: int, data: RespondBody, user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors can respond to trial requests.")
    booking = get_trial_booking_for_response(booking_id)
    if not booking or booking["tutor_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Trial request not found.")
    if booking["status"] != "pending":
        raise HTTPException(status_code=400, detail="You already answered this trial request.")
    new_status = "accepted" if data.action == "accept" else "declined"
    reason = validated_decline_reason(data)
    update_trial_booking_status(booking_id, new_status, reason)
    return {"message": "Trial request " + new_status + ".", "status": new_status}


@app.post("/trials/{booking_id}/contact-visibility")
def set_trial_contact_visibility_route(
    booking_id: int,
    data: ContactVisibilityBody,
    user: dict = Depends(get_current_user),
):
    booking = get_trial_booking_for_response(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Trial request not found.")
    if user["role"] == "student":
        owns_request = booking["student_id"] == user["id"]
    elif user["role"] == "tutor":
        owns_request = booking["tutor_user_id"] == user["id"]
    else:
        owns_request = False
    if not owns_request:
        raise HTTPException(status_code=404, detail="Trial request not found.")
    if booking["status"] != "accepted":
        raise HTTPException(status_code=400, detail="Contact visibility can be changed after acceptance.")
    if not set_trial_contact_visibility(booking_id, user["role"], data.visible):
        raise HTTPException(status_code=400, detail="This trial request is no longer accepted.")
    state = "visible" if data.visible else "hidden"
    return {"message": "Your contact details are now " + state + ".", "visible": data.visible}


@app.post("/requests/{request_id}/contact-visibility")
def set_contact_request_visibility_route(
    request_id: int,
    data: ContactVisibilityBody,
    user: dict = Depends(get_current_user),
):
    request = get_request_for_response(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found.")
    if user["role"] == "student":
        owns_request = request["student_id"] == user["id"]
    elif user["role"] == "tutor":
        owns_request = request["tutor_user_id"] == user["id"]
    else:
        owns_request = False
    if not owns_request:
        raise HTTPException(status_code=404, detail="Request not found.")
    if request["status"] != "accepted":
        raise HTTPException(status_code=400, detail="Contact visibility can be changed after acceptance.")
    if not set_contact_request_visibility(request_id, user["role"], data.visible):
        raise HTTPException(status_code=400, detail="This request is no longer accepted.")
    state = "visible" if data.visible else "hidden"
    return {"message": "Your contact details are now " + state + ".", "visible": data.visible}


def validate_tutoring_request(data: TutoringRequestBody, student_id: int):
    child_name = data.child_name.strip()
    requested_subjects = list(dict.fromkeys(
        subject.strip() for subject in data.subjects if subject.strip()
    ))
    message = data.message.strip()
    phone = clean_phone(data.phone)
    weekdays = list(dict.fromkeys(day.strip().title() for day in data.weekdays))
    allowed_weekdays = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

    if not child_name or len(child_name) > 60:
        raise HTTPException(status_code=400, detail="Student name is required (max 60 characters).")
    if phone is None:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number.")
    if not 1 <= data.class_level <= 12:
        raise HTTPException(status_code=400, detail="Class must be between 1 and 12.")
    if not requested_subjects:
        raise HTTPException(status_code=400, detail="Choose at least one subject.")
    if data.start_date < date.today():
        raise HTTPException(status_code=400, detail="The tutoring start date cannot be in the past.")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="The end date must be on or after the start date.")
    if not weekdays or any(day not in allowed_weekdays for day in weekdays):
        raise HTTPException(status_code=400, detail="Choose at least one valid day of the week.")
    if data.preferred_from >= data.preferred_to:
        raise HTTPException(status_code=400, detail="The preferred end time must be after the start time.")
    if len(message) > 300:
        raise HTTPException(status_code=400, detail="Message is too long (max 300 characters).")

    profile = get_public_tutor_profile(data.tutor_id, student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Tutor not found.")
    if not profile["is_accepting"]:
        raise HTTPException(status_code=400, detail="This tutor isn't taking new students right now.")
    if not profile["min_class"] <= data.class_level <= profile["max_class"]:
        raise HTTPException(status_code=400, detail="This tutor doesn't teach that class.")
    tutor_subjects = {subject.casefold(): subject for subject in profile["subjects"]}
    if any(subject.casefold() not in tutor_subjects for subject in requested_subjects):
        raise HTTPException(status_code=400, detail="This tutor doesn't teach one or more selected subjects.")
    requested_subjects = [tutor_subjects[subject.casefold()] for subject in requested_subjects]
    if (data.preferred_from < time(profile["available_from"]) or
            data.preferred_to > time(profile["available_to"])):
        raise HTTPException(status_code=400, detail="Choose times within the tutor's listed availability.")

    return (
        child_name, phone, data.class_level, requested_subjects, ", ".join(weekdays),
        data.preferred_from.strftime("%H:%M"), data.preferred_to.strftime("%H:%M"),
        data.start_date.isoformat(), data.end_date.isoformat(), message,
    )


@app.post("/booking-requests")
def request_tutoring(data: TutoringRequestBody, user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can request tutoring.")

    (child_name, phone, class_level, subjects, weekdays, preferred_from, preferred_to,
     start_date, end_date, message) = validate_tutoring_request(data, user["id"])
    request_id = create_tutoring_request(
        user["id"], data.tutor_id, child_name, phone, class_level, subjects,
        weekdays, preferred_from, preferred_to, start_date, end_date, message,
    )
    if request_id is None:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending tutoring request with this tutor for one or more selected subjects.",
        )
    return {"message": "Tutoring request sent. The tutor will review your schedule."}


@app.patch("/booking-requests/{request_id}")
def edit_tutoring_request(
    request_id: int, data: TutoringRequestBody, user: dict = Depends(get_current_user)
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can edit tutoring requests.")
    request = get_tutoring_request_for_response(request_id)
    if not request or request["student_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Tutoring request not found.")
    if request["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending tutoring requests can be edited.")
    if request["tutor_id"] != data.tutor_id:
        raise HTTPException(status_code=400, detail="The tutor cannot be changed on an existing request.")

    (child_name, phone, class_level, subjects, weekdays, preferred_from, preferred_to,
     start_date, end_date, message) = validate_tutoring_request(data, user["id"])
    result = update_tutoring_request(
        request_id, user["id"], data.tutor_id, child_name, phone, class_level,
        subjects, weekdays, preferred_from, preferred_to, start_date, end_date, message,
    )
    if result == "expired":
        raise HTTPException(status_code=400, detail="Tutoring requests can only be edited within 5 minutes of being sent.")
    if result == "duplicate":
        raise HTTPException(
            status_code=409,
            detail="You already have a pending tutoring request with this tutor for one or more selected subjects.",
        )
    return {"message": "Tutoring request updated."}


@app.get("/booking-requests/sent")
def my_tutoring_requests(user: dict = Depends(get_current_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students have tutoring requests.")
    return get_tutoring_requests_by_student(user["id"])


@app.get("/booking-requests/incoming")
def my_incoming_tutoring_requests(user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors have tutoring requests.")
    return get_incoming_tutoring_requests(user["id"])


@app.post("/booking-requests/{request_id}/respond")
def respond_to_tutoring_request(
    request_id: int, data: RespondBody, user: dict = Depends(get_current_user)
):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors can respond to tutoring requests.")
    request = get_tutoring_request_for_response(request_id)
    if not request or request["tutor_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Tutoring request not found.")
    if request["status"] != "pending":
        raise HTTPException(status_code=400, detail="You already answered this tutoring request.")
    new_status = "accepted" if data.action == "accept" else "declined"
    reason = validated_decline_reason(data)
    update_tutoring_request_status(request_id, new_status, reason)
    return {"message": "Tutoring request " + new_status + ".", "status": new_status}


@app.delete("/booking-requests/{request_id}")
def delete_tutoring_request(request_id: int, user: dict = Depends(get_current_user)):
    return delete_request("booking-requests", request_id, user)


@app.post("/booking-requests/{request_id}/contact-visibility")
def set_tutoring_contact_visibility_route(
    request_id: int,
    data: ContactVisibilityBody,
    user: dict = Depends(get_current_user),
):
    request = get_tutoring_request_for_response(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Tutoring request not found.")
    if user["role"] == "student":
        owns_request = request["student_id"] == user["id"]
    elif user["role"] == "tutor":
        owns_request = request["tutor_user_id"] == user["id"]
    else:
        owns_request = False
    if not owns_request:
        raise HTTPException(status_code=404, detail="Tutoring request not found.")
    if request["status"] != "accepted":
        raise HTTPException(status_code=400, detail="Contact visibility can be changed after acceptance.")
    if not set_tutoring_contact_visibility(request_id, user["role"], data.visible):
        raise HTTPException(status_code=400, detail="This tutoring request is no longer accepted.")
    state = "visible" if data.visible else "hidden"
    return {"message": "Your contact details are now " + state + ".", "visible": data.visible}


@app.post("/requests/{request_id}/respond")
def respond_to_request(request_id: int, data: RespondBody, user: dict = Depends(get_current_user)):
    if user["role"] != "tutor":
        raise HTTPException(status_code=403, detail="Only tutors can respond to requests.")

    req = get_request_for_response(request_id)
    # Same message whether it doesn't exist or belongs to another tutor
    if not req or req["tutor_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Request not found.")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="You already answered this request.")
    if data.action == "accept" and not req["tutor_phone"]:
        raise HTTPException(status_code=400, detail="Add your phone number in your profile first, so the student can reach you.")

    new_status = "accepted" if data.action == "accept" else "declined"
    reason = validated_decline_reason(data)
    update_request_status(request_id, new_status, reason)
    return {"message": "Request " + new_status + ".", "status": new_status}