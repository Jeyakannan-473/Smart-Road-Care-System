"""RoadCare Flask application: auth, complaints, workflow, messaging, maintenance queue."""
import os, sys, time, uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, abort, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from PIL import Image
except Exception:  # compiled Pillow blocked or missing: fall back to a header check
    Image = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
import c_bridge
from image_analysis import classifier

UPLOADS = os.path.join(ROOT, "uploads")
STATUSES = ["Submitted", "Under Review", "Approved", "In Progress", "Completed", "Rejected"]
FLOW = {"Submitted": ["Under Review", "Rejected"], "Under Review": ["Approved", "Rejected"],
        "Approved": ["In Progress", "Rejected"], "In Progress": ["Completed"], "Completed": [], "Rejected": []}
# Documented, configurable priority weights (sum = 100)
W = {"severity": 40, "road": 20, "repeat": 15, "age": 15, "verified": 10}
SEV = {"Low": .3, "Medium": .65, "High": 1.0}
ROAD = {"Highway": 1.0, "Arterial": .8, "Collector": .55, "Residential": .3}

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or sys.exit("Set SECRET_KEY in the environment (.env.example)."),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(ROOT, "roadcare.db")),
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", 8)) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1")
db = SQLAlchemy(app); csrf = CSRFProtect(app)
lm = LoginManager(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    locality = db.Column(db.String(100), index=True)
    city = db.Column(db.String(80))
    road_type = db.Column(db.String(20), default="Residential")
    description = db.Column(db.Text)
    phone = db.Column(db.String(20))
    lat = db.Column(db.Float); lng = db.Column(db.Float)
    image = db.Column(db.String(80))
    after_image = db.Column(db.String(80))
    status = db.Column(db.String(20), default="Submitted", index=True)
    ai_status = db.Column(db.String(30)); ai_category = db.Column(db.String(60))
    ai_severity = db.Column(db.String(10)); ai_confidence = db.Column(db.Float)
    needs_review = db.Column(db.Boolean, default=True)
    admin_verified = db.Column(db.Boolean, default=False)
    team = db.Column(db.String(80)); remarks = db.Column(db.Text)
    completion_note = db.Column(db.Text); completed_at = db.Column(db.DateTime)
    priority_score = db.Column(db.Float, default=0); priority_category = db.Column(db.String(10), default="Low")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    owner = db.relationship("User")
    @property
    def public_id(self): return f"RC-{self.created_at.year}-{self.id:06d}"

class StatusHistory(db.Model):  # append-only
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"), index=True)
    from_status = db.Column(db.String(20)); to_status = db.Column(db.String(20))
    changed_by = db.Column(db.Integer, db.ForeignKey("user.id")); remark = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"))
    title = db.Column(db.String(120)); body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):  # admin -> user only; recipient_id NULL = announcement
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"))
    body = db.Column(db.Text, nullable=False); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MessageRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id")); user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    __table_args__ = (db.UniqueConstraint("message_id", "user_id"),)

@lm.user_loader
def load_user(uid): return db.session.get(User, int(uid))
@lm.unauthorized_handler
def unauth(): return jsonify(error="Please sign in."), 401

def admin_required(f):
    @login_required
    def w(*a, **k):
        if current_user.role != "admin": return jsonify(error="Forbidden"), 403
        return f(*a, **k)
    w.__name__ = f.__name__; return w

def user_required(f):
    @login_required
    def w(*a, **k):
        if current_user.role != "user": return jsonify(error="Forbidden"), 403
        return f(*a, **k)
    w.__name__ = f.__name__; return w

def iso(d): return d.isoformat() + "Z" if d else None
def notify(uid, title, body, cid=None):
    db.session.add(Notification(user_id=uid, title=title, body=body, complaint_id=cid))

def priority(c):
    """Transparent weighted score 0-100. Returns (score, category, factor breakdown)."""
    repeats = Complaint.query.filter(Complaint.id != c.id, Complaint.locality == c.locality,
                                     Complaint.location == c.location, Complaint.status != "Completed").count()
    age = min((datetime.utcnow() - c.created_at).days, 30) / 30
    f = {"severity": SEV.get(c.ai_severity, .5), "road": ROAD.get(c.road_type, .3),
         "repeat": min(repeats, 5) / 5, "age": age, "verified": 1.0 if c.admin_verified else 0.0}
    parts = {k: round(W[k] * v, 1) for k, v in f.items()}; s = round(sum(parts.values()), 1)
    cat = "Critical" if s >= 80 else "High" if s >= 60 else "Medium" if s >= 35 else "Low"
    return s, cat, parts

def cdict(c, admin=False):
    d = dict(id=c.id, public_id=c.public_id, location=c.location, locality=c.locality, city=c.city,
             road_type=c.road_type, description=c.description, status=c.status, category=c.ai_category,
             severity=c.ai_severity, confidence=c.ai_confidence, ai_status=c.ai_status, needs_review=c.needs_review,
             remarks=c.remarks, completion_note=c.completion_note, completed_at=iso(c.completed_at),
             image=f"/files/{c.image}" if c.image else None, after_image=f"/files/{c.after_image}" if c.after_image else None, created_at=iso(c.created_at),
             priority_score=c.priority_score, priority_category=c.priority_category,
             history=[dict(from_status=h.from_status, to_status=h.to_status, remark=h.remark, at=iso(h.created_at))
                      for h in StatusHistory.query.filter_by(complaint_id=c.id).order_by(StatusHistory.id)])
    if admin: d.update(owner=c.owner.name, email=c.owner.email, team=c.team, verified=c.admin_verified,
                       breakdown=priority(c)[2])
    return d

# ---------- pages & files ----------
FRONT = os.path.join(ROOT, "frontend")
@app.get("/")
def home(): return send_from_directory(FRONT, "index.html")
@app.get("/<path:p>")
def static_files(p):
    if p.startswith("api/"): abort(404)
    return send_from_directory(FRONT, p)
@app.get("/files/<name>")
@login_required
def files(name):
    c = Complaint.query.filter((Complaint.image == name) | (Complaint.after_image == name)).first_or_404()
    if current_user.role != "admin" and c.user_id != current_user.id: abort(403)
    return send_from_directory(UPLOADS, name)
@app.get("/api/csrf")
def get_csrf(): return jsonify(token=generate_csrf())

# ---------- auth ----------
attempts = {}
def throttled(key):
    now = time.time(); attempts[key] = [t for t in attempts.get(key, []) if now - t < 300]
    return len(attempts[key]) >= 8

@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    name, email, pw = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("password") or ""
    if not (2 <= len(name) <= 80) or "@" not in email or len(email) > 120: return jsonify(error="Enter a valid name and email."), 400
    if len(pw) < 8: return jsonify(error="Password must be at least 8 characters."), 400
    if User.query.filter_by(email=email).first(): return jsonify(error="An account with this email already exists."), 409
    u = User(name=name, email=email, phone=(d.get("phone") or "")[:20], password_hash=generate_password_hash(pw))
    db.session.add(u); db.session.commit(); return jsonify(ok=True), 201

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    email, role = (d.get("email") or "").strip().lower(), d.get("role", "user")
    key = (request.remote_addr, email)
    if throttled(key): return jsonify(error="Too many attempts. Try again in a few minutes."), 429
    u = User.query.filter_by(email=email, role=role).first()
    if not u or not check_password_hash(u.password_hash, d.get("password") or ""):
        attempts.setdefault(key, []).append(time.time()); return jsonify(error="Incorrect email or password."), 401
    session.clear(); login_user(u)  # fresh session id prevents fixation
    return jsonify(role=u.role, name=u.name)

@app.post("/api/logout")
@login_required
def logout(): logout_user(); session.clear(); return jsonify(ok=True)
@app.get("/api/me")
@login_required
def me(): return jsonify(name=current_user.name, email=current_user.email, role=current_user.role)

# ---------- user: complaints ----------
@app.post("/api/complaints")
@user_required
def submit():
    f = request.form; loc = (f.get("location") or "").strip()
    if not loc or not (f.get("locality") or "").strip(): return jsonify(error="Road location and locality are required."), 400
    c = Complaint(user_id=current_user.id, location=loc[:200], locality=f["locality"].strip()[:100],
                  city=(f.get("city") or "")[:80], road_type=f.get("road_type") if f.get("road_type") in ROAD else "Residential",
                  description=(f.get("description") or "")[:2000], phone=(f.get("phone") or "")[:20])
    try: c.lat, c.lng = float(f["lat"]), float(f["lng"])
    except (KeyError, ValueError): pass
    result = {"status": "no_image", "stages": [], "needs_review": True}
    img = request.files.get("image")
    if img and img.filename:
        ext = os.path.splitext(img.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"): return jsonify(error="Only JPG, JPEG or PNG images are allowed."), 400
        if not valid_image(img.stream): return jsonify(error="The file is not a valid image."), 400
        name = uuid.uuid4().hex + ext; path = os.path.join(UPLOADS, name); img.save(path)
        result = classifier.analyse(path)
        if result["status"] == "rejected": os.remove(path); return jsonify(error=result["reason"], analysis=result), 422
        c.image = name
    c.ai_status, c.ai_category = result["status"], result.get("category")
    c.ai_severity, c.ai_confidence = result.get("severity"), result.get("confidence")
    c.needs_review = result.get("needs_review", True)
    db.session.add(c); db.session.flush()
    c.priority_score, c.priority_category, _ = priority(c)
    db.session.add(StatusHistory(complaint_id=c.id, from_status=None, to_status="Submitted", changed_by=current_user.id, remark="Complaint submitted"))
    notify(current_user.id, "Complaint submitted", f"Your complaint {c.public_id} was received.", c.id)
    db.session.commit(); return jsonify(complaint=cdict(c), analysis=result), 201

@app.get("/api/complaints")
@user_required
def my_complaints():
    q = Complaint.query.filter_by(user_id=current_user.id)  # users only ever see their own rows
    if request.args.get("status"): q = q.filter_by(status=request.args["status"])
    if request.args.get("q"): q = q.filter(Complaint.location.ilike(f"%{request.args['q'][:50]}%"))
    return jsonify(items=[cdict(c) for c in q.order_by(Complaint.id.desc()).all()])

@app.get("/api/complaints/<int:cid>")
@login_required
def complaint(cid):
    c = db.get_or_404(Complaint, cid)
    if current_user.role != "admin" and c.user_id != current_user.id: return jsonify(error="Not found"), 404
    return jsonify(cdict(c, current_user.role == "admin"))

# ---------- user: notifications & messages (read-only) ----------
@app.get("/api/notifications")
@user_required
def notifications():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.id.desc()).limit(50).all()
    return jsonify(items=[dict(id=n.id, title=n.title, body=n.body, complaint_id=n.complaint_id, read=n.is_read, at=iso(n.created_at)) for n in rows],
                   unread=sum(not n.is_read for n in rows))
@app.post("/api/notifications/<int:nid>/read")
@user_required
def read_notification(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first_or_404(); n.is_read = True; db.session.commit(); return jsonify(ok=True)

@app.get("/api/messages")
@user_required
def inbox():
    rows = Message.query.filter((Message.recipient_id == current_user.id) | (Message.recipient_id.is_(None))).order_by(Message.id.desc()).all()
    seen = {r.message_id for r in MessageRead.query.filter_by(user_id=current_user.id)}
    return jsonify(items=[dict(id=m.id, body=m.body, complaint_id=m.complaint_id, announcement=m.recipient_id is None, at=iso(m.created_at), read=m.id in seen) for m in rows],
                   unread=sum(m.id not in seen for m in rows))
@app.post("/api/messages/<int:mid>/read")
@user_required
def read_message(mid):
    m = db.get_or_404(Message, mid)
    if m.recipient_id not in (None, current_user.id): abort(404)
    if not MessageRead.query.filter_by(message_id=mid, user_id=current_user.id).first():
        db.session.add(MessageRead(message_id=mid, user_id=current_user.id)); db.session.commit()
    return jsonify(ok=True)
# Deliberately no user POST route for messages: users cannot send.

# ---------- admin ----------
@app.get("/api/admin/stats")
@admin_required
def stats():
    n = lambda s: Complaint.query.filter_by(status=s).count()
    by_sev = {s: Complaint.query.filter_by(ai_severity=s).count() for s in SEV}
    monthly = {}
    for c in Complaint.query.filter(Complaint.created_at > datetime.utcnow() - timedelta(days=183)):
        k = c.created_at.strftime("%b %Y"); monthly[k] = monthly.get(k, 0) + 1
    return jsonify(total=Complaint.query.count(), by_status={s: n(s) for s in STATUSES}, by_severity=by_sev, monthly=monthly,
                   high_priority=Complaint.query.filter(Complaint.priority_category.in_(["High", "Critical"]), Complaint.status.notin_(["Completed", "Rejected"])).count())

@app.get("/api/admin/complaints")
@admin_required
def admin_list():
    q = Complaint.query
    for k, col in (("status", Complaint.status), ("severity", Complaint.ai_severity)):
        if request.args.get(k): q = q.filter(col == request.args[k])
    if request.args.get("q"):
        like = f"%{request.args['q'][:50]}%"; q = q.filter(Complaint.location.ilike(like) | Complaint.locality.ilike(like))
    page = max(int(request.args.get("page", 1)), 1); p = q.order_by(Complaint.id.desc()).paginate(page=page, per_page=15, error_out=False)
    return jsonify(items=[cdict(c, True) for c in p.items], pages=p.pages)

@app.post("/api/admin/complaints/<int:cid>/status")
@admin_required
def set_status(cid):
    c = db.get_or_404(Complaint, cid); d = request.get_json(silent=True) or {}
    new, remark = d.get("status"), (d.get("remark") or "").strip()[:1000]
    if new not in FLOW.get(c.status, []): return jsonify(error=f"Cannot move from {c.status} to {new}."), 400
    if new == "Rejected" and not remark: return jsonify(error="A reason is required to reject a complaint."), 400
    old, c.status, c.remarks = c.status, new, remark or c.remarks
    if "team" in d: c.team = (d["team"] or "")[:80]
    if "verified" in d: c.admin_verified = bool(d["verified"])
    if d.get("category"): c.ai_category = d["category"][:60]
    if d.get("severity") in SEV: c.ai_severity = d["severity"]
    if new == "Completed": c.completed_at = datetime.utcnow(); c.completion_note = remark
    c.priority_score, c.priority_category, _ = priority(c)
    db.session.add(StatusHistory(complaint_id=c.id, from_status=old, to_status=new, changed_by=current_user.id, remark=remark))
    notify(c.user_id, f"Complaint {new}", f"{c.public_id} is now '{new}'." + (f" Remarks: {remark}" if remark else ""), c.id)
    db.session.commit(); return jsonify(complaint=cdict(c, True))

@app.get("/api/admin/queue")
@admin_required
def queue():
    open_ = Complaint.query.filter(Complaint.status.in_(["Approved", "In Progress"])).all()
    by_id = {c.id: c for c in open_}
    try:
        order = c_bridge.ordered_queue((c.id, c.priority_score, c.created_at.timestamp()) for c in open_)
    except c_bridge.CCoreError as e:
        return jsonify(error=str(e)), 503
    return jsonify(items=[dict(rank=i + 1, **cdict(by_id[x], True)) for i, x in enumerate(order)])

@app.post("/api/admin/messages")
@admin_required
def send_message():
    d = request.get_json(silent=True) or {}; body = (d.get("body") or "").strip()
    if not body or len(body) > 2000: return jsonify(error="Message must be 1-2000 characters."), 400
    uid = d.get("user_id")
    if uid and not User.query.filter_by(id=uid, role="user").first(): return jsonify(error="User not found."), 404
    db.session.add(Message(sender_id=current_user.id, recipient_id=uid or None, complaint_id=d.get("complaint_id"), body=body))
    if uid: notify(uid, "New message from RoadCare", body[:120], d.get("complaint_id"))
    else:
        for u in User.query.filter_by(role="user"): notify(u.id, "Announcement", body[:120])
    db.session.commit(); return jsonify(ok=True), 201

@app.get("/api/admin/users")
@admin_required
def users():
    q = User.query.filter_by(role="user")
    if request.args.get("q"): q = q.filter(User.name.ilike(f"%{request.args['q'][:40]}%") | User.email.ilike(f"%{request.args['q'][:40]}%"))
    return jsonify(items=[dict(id=u.id, name=u.name, email=u.email) for u in q.limit(20)])

@app.get("/api/admin/export.csv")
@admin_required
def export():
    import csv, io
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ID", "Location", "Locality", "Status", "Severity", "Priority", "Submitted"])
    for c in Complaint.query.order_by(Complaint.id):
        cell = lambda v: "'" + v if str(v)[:1] in "=+-@" else v  # CSV-injection guard
        w.writerow([c.public_id, cell(c.location), cell(c.locality), c.status, c.ai_severity, c.priority_score, c.created_at.strftime("%d-%m-%Y")])
    return out.getvalue(), 200, {"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=roadcare_report.csv"}


def valid_image(stream):
    """True if the upload is a real JPEG/PNG. Uses Pillow when available, otherwise checks the file signature."""
    try:
        if Image is not None:
            Image.open(stream).verify(); stream.seek(0); return True
        head = stream.read(12); stream.seek(0)
        return head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n")
    except Exception:
        return False

def save_image(img):
    """Validate (extension + real image header) and store with a random name. Returns (name, error)."""
    ext = os.path.splitext(img.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"): return None, "Only JPG, JPEG or PNG images are allowed."
    if not valid_image(img.stream): return None, "The file is not a valid image."
    name = uuid.uuid4().hex + ext; img.save(os.path.join(UPLOADS, name)); return name, None

# ---------- profile & password ----------
@app.get("/api/profile")
@login_required
def profile(): return jsonify(name=current_user.name, email=current_user.email, phone=current_user.phone, joined=iso(current_user.created_at))
@app.put("/api/profile")
@login_required
def update_profile():
    d = request.get_json(silent=True) or {}; name = (d.get("name") or "").strip()
    if not 2 <= len(name) <= 80: return jsonify(error="Enter a valid name."), 400
    current_user.name, current_user.phone = name, (d.get("phone") or "")[:20]; db.session.commit(); return jsonify(ok=True)
@app.post("/api/password")
@login_required
def change_password():
    d = request.get_json(silent=True) or {}
    if not check_password_hash(current_user.password_hash, d.get("current") or ""): return jsonify(error="Current password is incorrect."), 400
    if len(d.get("new") or "") < 8: return jsonify(error="New password must be at least 8 characters."), 400
    current_user.password_hash = generate_password_hash(d["new"]); db.session.commit(); return jsonify(ok=True)
@app.post("/api/forgot")
def forgot():
    # No email service is configured, so no reset link can be sent. The response is identical for any address
    # (prevents account enumeration). Admins can reset a password with: flask --app backend/app.py reset-password
    return jsonify(message="If this email is registered, the maintenance office will contact you to reset your password.")
@app.post("/api/notifications/read-all")
@user_required
def read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True}); db.session.commit(); return jsonify(ok=True)

# ---------- admin: verification, completion image, messages, analytics ----------
@app.post("/api/admin/complaints/<int:cid>/assign")
@admin_required
def assign(cid):
    c = db.get_or_404(Complaint, cid); d = request.get_json(silent=True) or {}
    if "team" in d: c.team = (d["team"] or "")[:80]
    if d.get("category"): c.ai_category = d["category"][:60]
    if d.get("severity") in SEV: c.ai_severity = d["severity"]
    if "verified" in d: c.admin_verified = bool(d["verified"]); c.needs_review = not c.admin_verified and c.needs_review
    c.priority_score, c.priority_category, _ = priority(c); db.session.commit(); return jsonify(complaint=cdict(c, True))

@app.post("/api/admin/complaints/<int:cid>/after-image")
@admin_required
def after_image(cid):
    c = db.get_or_404(Complaint, cid); img = request.files.get("image")
    if c.status != "Completed": return jsonify(error="Only completed complaints can have an after-maintenance image."), 400
    if not img or not img.filename: return jsonify(error="Choose an image."), 400
    name, err = save_image(img)
    if err: return jsonify(error=err), 400
    c.after_image = name; db.session.commit(); return jsonify(complaint=cdict(c, True))

@app.get("/api/admin/messages")
@admin_required
def sent_messages():
    total = User.query.filter_by(role="user").count(); q = Message.query
    if request.args.get("q"): q = q.filter(Message.body.ilike(f"%{request.args['q'][:50]}%"))
    out = []
    for m in q.order_by(Message.id.desc()).limit(100):
        r = User.query.get(m.recipient_id) if m.recipient_id else None
        out.append(dict(id=m.id, body=m.body, to=r.name if r else "All users", complaint_id=m.complaint_id, at=iso(m.created_at),
                        read=MessageRead.query.filter_by(message_id=m.id).count(), audience=1 if r else total))
    return jsonify(items=out)

@app.get("/api/admin/analytics")
@admin_required
def analytics():
    cs = Complaint.query.all(); done = [c for c in cs if c.completed_at]
    area, monthly_done = {}, {}
    for c in cs: area[c.locality or "Unknown"] = area.get(c.locality or "Unknown", 0) + 1
    for c in done: k = c.completed_at.strftime("%b %Y"); monthly_done[k] = monthly_done.get(k, 0) + 1
    hot = sorted((c for c in cs if c.status not in ("Completed", "Rejected")), key=lambda c: -c.priority_score)[:8]
    return jsonify(by_area=area, by_severity={s: sum(c.ai_severity == s for c in cs) for s in SEV},
                   pending=sum(c.status not in ("Completed", "Rejected") for c in cs), completed=len(done), monthly_completed=monthly_done,
                   avg_resolution_days=round(sum((c.completed_at - c.created_at).total_seconds() for c in done) / len(done) / 86400, 1) if done else None,
                   hot=[dict(id=c.id, public_id=c.public_id, location=c.location, locality=c.locality, score=c.priority_score) for c in hot])

@app.cli.command("reset-password")
def reset_password():
    """Admin-assisted reset: flask --app backend/app.py reset-password"""
    import click, getpass
    u = User.query.filter_by(email=click.prompt("User email").strip().lower()).first()
    if not u: raise click.ClickException("No such user.")
    pw = getpass.getpass("New password (min 8 chars): ")
    if len(pw) < 8: raise click.ClickException("Password too short.")
    u.password_hash = generate_password_hash(pw); db.session.commit(); click.echo("Password updated.")

@app.cli.command("create-admin")
def create_admin():
    """Secure admin setup: flask --app backend/app.py create-admin"""
    import click, getpass
    email = click.prompt("Admin email").strip().lower(); name = click.prompt("Admin name")
    pw = getpass.getpass("Password (min 10 chars): ")
    if len(pw) < 10: raise click.ClickException("Password too short.")
    db.session.add(User(name=name, email=email, role="admin", password_hash=generate_password_hash(pw))); db.session.commit()
    click.echo("Admin created.")

with app.app_context(): os.makedirs(UPLOADS, exist_ok=True); db.create_all()
if __name__ == "__main__": app.run(debug=False, port=5000)
