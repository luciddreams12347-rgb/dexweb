# DeX Web

DeX Web is a Flask website with a terminal-style design, login/account creation, cipher and ASCII art tools, grade-based chat rooms, and a simple admin panel for users, bans, and logs.

The app is organized as a normal Python package so it can grow into a larger platform. New features should live under `dexweb/features/<feature_name>/` with their own routes, services, templates, tests, and database changes.

DEX is now available as the central AI service under `dexweb/features/dex/`. See `DEX.md` for admin controls, prompt management, and future provider integration.

## Project Structure

```text
dexweb/
├── api/                    # Vercel adapter
├── database/               # SQL schema and future migrations
├── dexweb/                 # Flask application package
│   ├── features/           # Feature modules
│   │   ├── admin/
│   │   ├── auth/
│   │   ├── chat/
│   │   ├── core/
│   │   ├── dex/
│   │   └── tools/
│   ├── static/             # CSS and JavaScript
│   ├── templates/          # Jinja templates
│   ├── config.py           # Environment-backed settings
│   ├── database.py         # MySQL access helpers
│   └── routes.py           # Shared blueprint registration
├── tests/                  # Automated tests
├── .env.example            # Environment variable template
├── DATABASE_SETUP.md       # MySQL setup guide
├── Dockerfile              # Container deployment
├── Procfile                # Render/Replit-style process command
├── requirements.txt        # Production Python dependencies
├── requirements-dev.txt    # Test/development dependencies
├── wsgi.py                 # Production WSGI entrypoint
└── Dexweb.py               # Local compatibility entrypoint
```

`backup_original_project/` contains the original files that were removed or moved during cleanup. Do not upload that folder to public hosting.

## Required Software

- Python 3.12 or newer
- `pip`
- Optional: MySQL or MariaDB for production accounts/logs/bans

## Install Locally

From the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Environment Setup

1. Copy `.env.example` to `.env`.
2. Fill in at least:

```bash
APP_SECRET=replace-with-a-long-random-secret
ADMIN_PASSWORD=replace-with-a-strong-admin-password
DEX_DB_ENABLED=false
```

For production, set these variables in the hosting dashboard instead of committing `.env`.

Important variables:

- `APP_SECRET`: signs browser sessions. Change this in production.
- `ADMIN_PASSWORD`: password for `/admin_login`.
- `DATABASE_URL`: recommended one-line MySQL URL.
- `DEX_DB_ENABLED`: set `true` when using separate database variables.
- `DEX_DB_HOST`, `DEX_DB_PORT`, `DEX_DB_USER`, `DEX_DB_PASSWORD`, `DEX_DB_NAME`: MySQL connection parts.
- `PORT`: hosting providers usually set this automatically.
- `DEX_SYSTEM_PROMPT_PATH`: optional writable path for the active DEX system prompt.
- `DEX_PROVIDER`: future AI provider selector; defaults to `local-placeholder`.
- `DEX_MODEL`: future AI model name.

## Database Setup

The site can run without a database for demos, but production should use MySQL so accounts, logs, and bans persist.

Read `DATABASE_SETUP.md`, then run:

```bash
mysql -u your_user -p your_database < database/schema.sql
```

After the schema exists, set either:

```bash
DATABASE_URL=mysql+pymysql://user:password@host:3306/database_name
```

or:

```bash
DEX_DB_ENABLED=true
DEX_DB_HOST=host
DEX_DB_PORT=3306
DEX_DB_USER=user
DEX_DB_PASSWORD=password
DEX_DB_NAME=database_name
```

## Run Locally

Without a database:

```bash
python Dexweb.py
```

Then open:

```text
http://127.0.0.1:5000
```

Production-style local run:

```bash
gunicorn --bind 0.0.0.0:5000 wsgi:app
```

On Windows, Gunicorn is not supported. Use `python Dexweb.py` locally and use Gunicorn on Linux hosting.

## Test

```bash
python -m pytest tests -v
```

Run tests before every deployment.

## Recommended Hosting Options

Best fit:

- Render Web Service: good for Flask with `Procfile`; use external MySQL.
- PythonAnywhere: good for Flask plus managed MySQL.
- Replit: easy upload and run; use Secrets for environment variables.
- Docker-based hosting: use the included `Dockerfile`.

Possible but less ideal:

- Vercel: included `api/index.py` and `vercel.json` can run the Flask app as serverless Python. In-memory chat messages may disappear between requests because serverless instances are temporary. Use a database-backed chat store before relying on Vercel for chat-heavy production use.

## Publish Online

### Render

1. Push this folder to a GitHub repository.
2. Create a Render Web Service from that repository.
3. Use these settings:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn --bind 0.0.0.0:$PORT wsgi:app`
4. Add environment variables from `.env.example`.
5. Connect MySQL using `DATABASE_URL` or the `DEX_DB_*` variables.
6. Deploy.

### PythonAnywhere

1. Upload the project folder or clone it with Git.
2. Create a virtualenv and run `pip install -r requirements.txt`.
3. Create a PythonAnywhere Flask web app.
4. Point the WSGI file to `wsgi.py` and expose `application = app` if PythonAnywhere asks for `application`.
5. Create a MySQL database and run `database/schema.sql`.
6. Set environment variables in the WSGI file or PythonAnywhere web app settings.
7. Reload the web app.

### Replit

1. Upload or import the project.
2. Install dependencies with `pip install -r requirements.txt`.
3. Add Secrets from `.env.example`.
4. Set the run command to `python Dexweb.py` or `gunicorn --bind 0.0.0.0:$PORT wsgi:app`.
5. Use an external MySQL provider for production data.

### Docker

```bash
docker build -t dexweb .
docker run --env-file .env -p 5000:5000 dexweb
```

## Update The Website After Changes

1. Edit the code locally.
2. Add or update tests for the changed behavior.
3. Run `python -m pytest tests -v`.
4. Commit the changes to Git.
5. Push to your hosting repository or upload the changed files.
6. Restart or redeploy the hosting service.
7. Check the live site and admin login.

If database tables change, add a new SQL file in `database/` and run it on the production database before or during deployment.

## Add Future Features Safely

Use this pattern:

1. Create `dexweb/features/new_feature/`.
2. Put page handlers in `routes.py`.
3. Put business logic in a separate service file.
4. Put database access in `dexweb/database.py` or a focused database helper.
5. Add templates under `dexweb/templates/`.
6. Add CSS/JS under `dexweb/static/`.
7. Import the feature routes in `dexweb/routes.py`.
8. Add tests under `tests/`.

Keep secrets in environment variables only. Do not hard-code passwords, database hosts, API keys, or admin credentials.

For future AI-powered features, call `get_dex_service().process(...)` from `dexweb.features.dex.service` instead of creating a separate AI integration. DEX centralizes system prompt handling, provider selection, runtime reset behavior, and structured responses.

## Troubleshooting

- `ModuleNotFoundError: dexweb`: run commands from the project root, the folder containing `wsgi.py`.
- Login works locally but not after restart: enable MySQL; demo mode stores no users.
- Admin panel shows empty users/logs: database mode is off or the schema was not created.
- Database connection fails: verify host, port, username, password, database name, and network access from the host.
- Static files do not load: confirm the `dexweb/static/` folder was uploaded.
- Vercel chat messages disappear: use a persistent database-backed chat implementation before production use.
