import os, sys, tempfile
os.environ.update(SECRET_KEY="test", DATABASE_URL="sqlite://", WTF_CSRF_ENABLED="0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import pytest, app as A
from werkzeug.security import generate_password_hash

@pytest.fixture()
def c():
    A.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with A.app.app_context():
        A.db.drop_all(); A.db.create_all()
        A.db.session.add(A.User(name="Admin", email="a@x.in", role="admin", password_hash=generate_password_hash("adminpass12")))
        A.db.session.add(A.User(name="U1", email="u1@x.in", password_hash=generate_password_hash("password1")))
        A.db.session.add(A.User(name="U2", email="u2@x.in", password_hash=generate_password_hash("password2")))
        A.db.session.commit()
    return A.app.test_client()

def login(c, e, p, role="user"): return c.post("/api/login", json={"email": e, "password": p, "role": role})

def test_wrong_password(c): assert login(c, "u1@x.in", "nope").status_code == 401
def test_user_cannot_use_admin_api(c):
    login(c, "u1@x.in", "password1"); assert c.get("/api/admin/stats").status_code == 403
def test_user_cannot_send_message(c):
    login(c, "u1@x.in", "password1"); assert c.post("/api/messages", json={"body": "x"}).status_code in (404, 405)
    assert c.post("/api/admin/messages", json={"body": "x"}).status_code == 403
def test_admin_login_requires_admin_role(c): assert login(c, "u1@x.in", "password1", "admin").status_code == 401
def test_user_isolation_and_status_workflow(c):
    with A.app.app_context():
        cp = A.Complaint(user_id=2, location="MG Road", locality="Anna Nagar", ai_severity="High"); A.db.session.add(cp); A.db.session.commit(); cid = cp.id
    login(c, "u2@x.in", "password2"); assert c.get(f"/api/complaints/{cid}").status_code == 404
    assert c.post(f"/api/admin/complaints/{cid}/status", json={"status": "Approved"}).status_code == 403
    c.post("/api/logout"); login(c, "a@x.in", "adminpass12", "admin")
    assert c.post(f"/api/admin/complaints/{cid}/status", json={"status": "Completed"}).status_code == 400  # illegal jump
    assert c.post(f"/api/admin/complaints/{cid}/status", json={"status": "Under Review"}).status_code == 200
    c.post("/api/logout"); login(c, "u1@x.in", "password1")
    assert any(n["title"] == "Complaint Under Review" for n in c.get("/api/notifications").json["items"])
def test_c_priority_queue():
    import c_bridge; assert c_bridge.ordered_queue([(1, 50, 100), (2, 80, 200), (3, 80, 150)]) == [3, 2, 1]
def test_bad_upload_rejected(c):
    login(c, "u1@x.in", "password1"); import io
    r = c.post("/api/complaints", data={"location": "x", "locality": "y", "image": (io.BytesIO(b"nope"), "a.png")}, content_type="multipart/form-data")
    assert r.status_code == 400

def test_admin_only_endpoints(c):
    login(c, "u1@x.in", "password1")
    for url in ("/api/admin/analytics", "/api/admin/messages", "/api/admin/queue", "/api/admin/export.csv"):
        assert c.get(url).status_code == 403
def test_forgot_password_is_generic(c):
    a, b = c.post("/api/forgot", json={"email": "u1@x.in"}), c.post("/api/forgot", json={"email": "nobody@x.in"})
    assert a.json == b.json
def test_admin_message_reaches_user_read_only(c):
    login(c, "a@x.in", "adminpass12", "admin"); assert c.post("/api/admin/messages", json={"body": "Hello", "user_id": 2}).status_code == 201
    c.post("/api/logout"); login(c, "u1@x.in", "password1")
    assert c.get("/api/messages").json["unread"] == 1
