# Database Setup

DeX Web can run without a database for local demos, but production accounts, audit logs, and bans need MySQL.

## Required Database

- Type: MySQL or MariaDB
- Python driver: PyMySQL
- Schema file: `database/schema.sql`

## Create The Database

### PythonAnywhere

1. Open the PythonAnywhere Databases tab.
2. Create a MySQL database, for example `yourusername$dexweb`.
3. Open a MySQL console for that database.
4. Paste and run the contents of `database/schema.sql`.
5. Add these environment variables in your WSGI file or web app environment:

```bash
DEX_DB_ENABLED=true
DEX_DB_HOST=yourusername.mysql.pythonanywhere-services.com
DEX_DB_PORT=3306
DEX_DB_USER=yourusername
DEX_DB_PASSWORD=your-database-password
DEX_DB_NAME=yourusername$dexweb
```

### Render

Render does not provide managed MySQL. Use an external MySQL provider such as PlanetScale, Aiven, Railway, or a cloud database, then set:

```bash
DATABASE_URL=mysql+pymysql://user:password@host:3306/database_name
```

Run `database/schema.sql` in your provider's SQL console before turning on public traffic.

### Replit

Use an external MySQL provider, then add `DATABASE_URL` or the `DEX_DB_*` variables in Replit Secrets.

### Local MySQL

```bash
mysql -u root -p -e "CREATE DATABASE dexweb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p dexweb < database/schema.sql
```

Then create a local `.env` file from `.env.example` and fill in either `DATABASE_URL` or the `DEX_DB_*` values.

## Environment Variables

- `DATABASE_URL`: One-line MySQL URL. If set, database mode turns on automatically.
- `DEX_DB_ENABLED`: Set to `true` when using separate `DEX_DB_*` variables.
- `DEX_DB_HOST`: MySQL hostname.
- `DEX_DB_PORT`: MySQL port, usually `3306`.
- `DEX_DB_USER`: MySQL username.
- `DEX_DB_PASSWORD`: MySQL password.
- `DEX_DB_NAME`: MySQL database name.

Do not commit real passwords or secrets.
