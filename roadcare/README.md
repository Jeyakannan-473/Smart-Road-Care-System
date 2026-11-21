# RoadCare - Report. Track. Repair.
## Setup
```
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt
cd c_core && make && cd ..                               # Windows (MinGW): make OUT=libroadcare_ds.dll
cp .env.example .env                                     # then set SECRET_KEY, and export the variables
export SECRET_KEY=...                                    # Windows: set SECRET_KEY=...
flask --app backend/app.py create-admin                  # prompts for admin email/password
python backend/app.py                                    # http://127.0.0.1:5000
pytest tests
```
## Image model
Put an ONNX image classifier at `image_analysis/models/road_damage.onnx` and a `labels.json` list of class names in the same folder
(input 1x3xHxW, logits output). Without them the app marks every report "manual review" - it never invents a result.
Edit `SEVERITY` in `image_analysis/classifier.py` to map your class names to Low/Medium/High.
## Priority score (0-100)
`40*severity + 20*road type + 15*repeat reports + 15*age (max 30 days) + 10*admin verified`. Weights: `W` in `backend/app.py`.
Queue order (C): higher score, then earlier submission, then lower ID.
## Notes
- Forgot password: no email service is configured, so the page gives a generic reply; an admin resets passwords with
  `flask --app backend/app.py reset-password`. Wire in SMTP later if you want self-service reset links.
- Passwords on first run: none exist. Create the admin with `create-admin`, then register citizens in the browser.
- Delete `roadcare.db` if you change models (this project does not use migrations).
- Set `COOKIE_SECURE=1` when serving over HTTPS.
