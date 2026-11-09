# Nexora — WhatsApp Sales Assistant

A university project for small shops: answer customer questions on WhatsApp,
check products and stock, take orders, and manage them from a website.

For the detailed file guide, implementation contracts, UI specification, and
rebuild checklist, see [Nexora Technical Reference](NEXORA_TECHNICAL_REFERENCE.md).

## 1. The three main folders

```text
nexora/
├── backend/                  Python application and WhatsApp connection
│   ├── core/                 Six main Python modules (explained below)
│   │   └── migrations/       Django's database schema history
│   ├── nexora/               Django settings and website URLs
│   ├── whatsapp/
│   │   ├── index.js          The single Node.js bridge file
│   │   ├── test.js           WhatsApp lifecycle checks with fake sockets
│   │   ├── package.json      Node dependencies
│   │   ├── package-lock.json Exact Node dependency versions
│   │   ├── node_modules/     Installed libraries
│   │   └── sessions/         Saved WhatsApp logins
│   ├── .venv/                Installed Python environment
│   ├── .env                  Your local configuration
│   ├── .env.example          Configuration template
│   ├── requirements.txt      Python dependencies
│   ├── manage.py             Django command entry point
│   ├── seed_demo.py          Optional sample accounts and products
│   └── smoke_test.py         Offline checks using a temporary database
├── frontend/                 Everything displayed by the website
│   ├── templates/            HTML pages
│   ├── static/               JavaScript, CSS, fonts, and favicon
│   └── media/                Uploaded product photos
├── database/
│   └── setup.sql             One-time XAMPP database creation
├── start.bat                 Windows launcher
├── start.sh                  macOS/Linux launcher
├── start_mac.command         macOS double-click shortcut
└── README.md                 This guide
```

The frontend is served by Django. There is no separate frontend server or build
step. Database models and migrations belong to the backend because they describe
the data. XAMPP's MySQL/MariaDB server stores the records in **`nexora_app`**;
`database/setup.sql` creates that database on a new computer.

## 2. Run the project

### Windows — this existing copy

Start **MySQL** in the XAMPP Control Panel. Then double-click `start.bat`, or run
it in the project folder:

```bat
start.bat
```

Open **http://127.0.0.1:8000/**. Close the two server windows to stop Nexora.
Normal startup applies existing migrations and starts the services. It does not
reset accounts, generate migrations, seed demo data, or reinstall dependencies.

### First setup on another computer

1. Install Python 3.11+, a current Node.js LTS release, and XAMPP.
2. Start **MySQL** and **Apache** in XAMPP. Open
   **http://localhost/phpmyadmin/** and import `database/setup.sql` to create
   `nexora_app`.
3. Run these commands from the project folder:

```bat
start.bat setup
start.bat
```

Setup creates the Python environment if needed and installs the libraries listed
in `requirements.txt` and `package-lock.json`. It copies `.env.example` to `.env`
only when `.env` is missing. Internet access is needed to install dependencies.
The default XAMPP connection is `root`, an empty password, and port `3306`.
If yours differs, edit the `DB_*` values in `backend/.env` before starting.

### macOS / Linux

Use an environment installed on that operating system, rather than copying the
Windows `.venv` or `node_modules` folders.
Start MySQL in XAMPP and import `database/setup.sql` as above, then run:

```bash
bash start.sh setup
bash start.sh
```

Open **http://127.0.0.1:8000/**. Press Ctrl+C to stop the services. On macOS,
`start_mac.command` is a shortcut to the same launcher.

### Optional demo accounts

On a fresh database, create the sample data explicitly:

```bat
backend\.venv\Scripts\python.exe backend\seed_demo.py
```

On macOS/Linux use `backend/.venv/bin/python backend/seed_demo.py`.

| Account | Username | Initial demo password |
|---|---|---|
| System administrator | `admin` | `Admin123` |
| Zara Fashion | `zara` | `Zara1234` |
| Mr. Perfect | `mrperfect` | `Perfect1` |

These defaults apply only to newly created demo accounts. Running the command
again keeps existing accounts, passwords, products, orders, and conversations.
Real businesses can use the signup page or be created by the administrator.

## 3. Configure the working features

- **AI:** Sign in as an administrator and open **AI provider**. Save your provider
  URL, API key, and model, then test the connection. `.env` can also supply defaults.
- **WhatsApp:** Sign in as a shop, open **Settings**, and click **Connect WhatsApp**.
  Scan the QR code using WhatsApp's Linked devices feature. Saved logins reconnect
  when the bridge starts. Checking status is read-only; connecting is explicit.
  The browser uses authenticated Django endpoints, and the Node bridge listens
  locally on `127.0.0.1:3001`.
- **Customer photos:** Use an AI model/provider that accepts image inputs. Customers
  can send a photo with a caption or ask about it in a separate message during the
  active chat. The WhatsApp bridge processes each customer's messages in order,
  including photo downloads and completed agent replies, so a quick follow-up
  cannot overtake its photo. Other customers' chats remain independent.
  Only the latest photo is held temporarily in backend memory; a new
  photo replaces it, it expires after 10 minutes of chat inactivity, and restarting
  the backend forgets it. Incoming image bytes are not saved in conversation history
  or as uploaded files. Context is local to one backend process and bounded to 16
  chats and 4 MiB of base64 per photo; older contexts may be evicted when full, and
  larger photos are not retained for subsequent questions.
  Recognising the object in a photo is separate from identifying an exact catalogue
  item/SKU; the assistant must verify a catalogue match before confirming its stock.
- **Email verification:** Stytch B2B sends signup and password-reset codes. Set
  `STYTCH_PROJECT_ID`, `STYTCH_SECRET`, `STYTCH_ORGANIZATION_ID`, and `STYTCH_ENV`
  in `backend/.env`, with `EMAIL_OTP_BACKEND=stytch`. The restored `email-auth.md`
  is a private credential reference. Stytch's test environment still sends email.
  For a local demonstration without email, explicitly choose
  `EMAIL_OTP_BACKEND=dev` and `DJANGO_DEBUG=1`; the verification page then displays
  the development code. Missing Stytch configuration reports a delivery error.
- **Pathao shipping:** In the shop's **Settings**, enter your merchant credentials,
  test the connection, and copy the correct pickup **Store ID** from the result.
  Enable Pathao and save. Sandbox is for testing; select Production for real
  bookings. Orders send the full delivery address for Pathao's address detection.
  The connection test reads account/store information without creating a shipment.
- **Manual delivery:** Leave **Enable Pathao** switched off. Shipping then records
  delivery arranged by the shop, without a courier booking or tracking number.

To view the current records, start Apache in XAMPP and select **`nexora_app`** in
phpMyAdmin. Keep MySQL running while Nexora is in use. The Django settings include
a small compatibility adjustment for XAMPP's MariaDB 10.4; the MySQL smoke command
below checks this application's queries on that server.

Product photos stay in `frontend/media/`; the database stores their URLs.
Replacing a photo or deleting a business removes unused local images after the
database change commits. Images referenced by another product or a saved chat
are retained, including photos on archived products.

## 4. How an order works

1. A customer messages the connected WhatsApp account.
2. The Node bridge passes the message to Django.
3. The AI calls the inventory/order functions in `agent.py`.
4. A confirmed customer request creates a **Pending** order and reserves stock.
5. The shop clicks **Accept**. The order appears under **Active Orders**.
6. The shop clicks **Ship**. Nexora books Pathao when enabled, or records manual
   delivery. A failed booking leaves the order accepted and displays the error.
7. The shop marks a shipped order **Complete** from its details or order history.

Accepting and shipping are separate steps. Pending and accepted orders can be
cancelled, which returns their reserved stock. A failed WhatsApp notification
is reported separately from the saved order change.

Order history includes accepted, shipped, cancelled, and completed orders. Records
marked as simulated are labelled as demo tracking. Refresh the page
to retrieve orders or messages received since the last dashboard load.

## 5. The code to understand first

There are **ten main application-code files** to read. The HTML templates and
Django configuration sit alongside them.

| File | Its job |
|---|---|
| `backend/core/models.py` | Describes businesses, products, orders, conversations, and plan limits; includes stock helpers. |
| `backend/core/views.py` | Receives website/API requests, checks permissions, and performs actions. |
| `backend/core/agent.py` | Calls the AI provider and implements the AI's inventory/order tools. |
| `backend/core/email_auth.py` | Sends/verifies email codes and checks password rules. |
| `backend/core/couriers.py` | Books Pathao shipments and records manual shipping. |
| `backend/core/widgets.py` | Builds the data displayed on the dashboards. |
| `backend/whatsapp/index.js` | Connects WhatsApp to Django and sends replies/media. |
| `frontend/static/app.js` | Handles buttons, forms, tables, and dashboard requests. |
| `frontend/static/charts.js` | Draws the small dashboard charts using SVG. |
| `frontend/static/style.css` | Defines the website's appearance. |

Useful supporting files:

- `backend/nexora/urls.py`: maps each URL to a function in `views.py`.
- `backend/nexora/settings.py`: tells Django where the frontend, database, uploads,
  and configuration live.
- `frontend/templates/`: five files — `landing.html`, `client.html`, `admin.html`,
  `404.html`, and `auth.html`. The shared auth template shows login, signup,
  password reset, or code verification according to the view's `screen` value.
- `backend/core/migrations/`: Django's ordered instructions for creating/updating
  tables. Keep these with the code so existing databases remain compatible.
- `__init__.py`, `apps.py`, `manage.py`, and `wsgi.py`: small Python/Django setup files.

Follow one example when explaining the project: the Accept button in `app.js`
calls `/api/order/<id>/action/`; `urls.py` routes it to `order_action` in `views.py`;
that function updates the `Order` model, attempts the WhatsApp notification, and
returns JSON for the dashboard to refresh.

## 6. GitHub references and attribution

Nexora uses these open-source libraries. Their repositories are appropriate
references for the infrastructure they provide:

| Project | What Nexora uses it for | License |
|---|---|---|
| [Django](https://github.com/django/django) | Web server framework, routing, templates, login sessions, ORM, and migrations. | BSD-3-Clause |
| [Baileys](https://github.com/WhiskeySockets/Baileys) | WhatsApp connection, authentication state, messages, and media. | MIT |
| [Express](https://github.com/expressjs/express) | The Node bridge's HTTP endpoints. | MIT |
| [node-qrcode](https://github.com/soldair/node-qrcode) | Converts the WhatsApp login QR code into an image. | MIT |
| [Requests](https://github.com/psf/requests) | Python HTTP calls to AI, email, courier, and bridge services. | Apache-2.0 |
| [PyMySQL](https://github.com/PyMySQL/PyMySQL) | Connects Django to XAMPP's MySQL/MariaDB server. | MIT |
| [Geist](https://github.com/vercel/geist-font) | Geist and Geist Mono website fonts. | SIL OFL 1.1 |
| [Instrument Serif](https://github.com/Instrument/instrument-serif) | Website heading font. | SIL OFL 1.1 |

An accurate presentation summary:

> Nexora builds on Django for the web application and database access, and Baileys
> for WhatsApp connectivity. The Nexora-specific code connects those libraries to
> the AI inventory/order tools, business dashboards, and courier workflow.

These are dependency credits. They do not establish that Nexora's custom screens
or business rules were copied from those repositories. Library license notices
remain in the installed packages; the bundled fonts' notice is in
`frontend/static/fonts/OFL.txt`.

Provider references: [Stytch B2B email OTP](https://stytch.com/docs/b2b/api/authenticate-email-otp)
and [Pathao automatic address detection](https://pathao.com/bn/blog/api-merchant-auto-address-feature/).

## 7. Check that changes still work

From the project root on Windows:

```bat
backend\.venv\Scripts\python.exe backend\manage.py check --database default
backend\.venv\Scripts\python.exe backend\smoke_test.py
backend\.venv\Scripts\python.exe -B backend\test_agent_images.py
backend\.venv\Scripts\python.exe backend\smoke_test.py --mysql
node --test backend/whatsapp/test.js
node --check frontend/static/app.js
node --check backend/whatsapp/index.js
```

The smoke script creates an in-memory SQLite database and temporary uploads, and
stubs external HTTP calls. It checks authentication, catalog/stock operations,
permissions, orders, courier success/failure, photo cleanup, and non-destructive
demo setup. `--mysql` runs the same checks in a uniquely named temporary MySQL
database and removes it afterwards; start XAMPP MySQL first. The Node checks use
fake WhatsApp sockets and temporary session folders. These checks leave the
saved records and WhatsApp login alone and make no external API calls.
The bridge tests also cover delayed photo downloads, ordered follow-up requests,
independent customer chats, failed requests and cancellation of old queued sessions.
The focused image tests exercise both AI request formats, temporary photo context,
expiry/replacement, chat isolation, and catalogue-photo tools with live network and
database access disabled.

Also check the real browser buttons: Accept → Active Orders → Ship → Complete;
Cancel should restore stock once; the administrator's business drawer should
open, save a plan, and close. Live WhatsApp, email, AI, and courier connections
need their own configured accounts and internet access.

## 8. What belongs in a source submission

Include the application code, templates, styles/fonts, migrations, dependency
lists, `.env.example`, launchers, and this README. Dependencies are installed by
setup, so `.venv`, `node_modules`, and Python caches can be left out of the source
archive. Keep private `.env` values, `email-auth.md`, and saved WhatsApp sessions with your local
working installation. Decide separately whether the submission needs demo data
and product photos; the database and uploads are runtime data, not unused code.
