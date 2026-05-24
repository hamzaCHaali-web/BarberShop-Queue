# Hala9 — Smart Queue & Barbershop Management

A bilingual (Arabic/English) barbershop queue management system with a public portfolio page, customer self-service queue, and admin dashboard.

## Features

### Customer App (`/app`)
- Join the queue with your name — get a queue number and position
- Track your spot in real-time with estimated wait time
- See who's currently being served
- Leave the queue anytime
- Responsive mobile & desktop layouts

### Admin Panel (`/admin`)
- **Dashboard** — View/manage queue: finish, skip, pause (lunch/break/prayer/busy), resume, reset, toggle shop open/closed
- **Settings** — Change admin password
- **Shop Settings** — Edit shop name, hero title/description, social links (Instagram, Facebook, YouTube, WhatsApp), phone, location, working hours
- **Statistics** — Charts with period filtering (day/week/month/year): bar chart breakdown, donut pie chart distribution, 30-day trend line chart

### Public Portfolio (`/`)
- Hero section with animated shop name and description
- Services, gallery, team, testimonials sections
- Social media links, contact info, working hours
- Scroll reveal animations

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18, Vite, Tailwind CSS, React Router |
| Backend | Flask (Python), SQLite |
| Charts | Recharts |
| Icons | Lucide React, React Icons (Font Awesome) |
| Auth | Server-side sessions (signed cookies) |

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

The server starts on `http://localhost:5000`. The database is auto-created with a default shop and admin user.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server starts on `http://localhost:5173` and proxies `/api` requests to the Flask backend.

### 3. Open in Browser

| URL | Page |
|-----|------|
| `http://localhost:5173` | Public portfolio page |
| `http://localhost:5173/app` | Customer queue app |
| `http://localhost:5173/admin` | Admin login |

### Default Admin Credentials

```
Username: admin
Password: admin123
```

## Project Structure

```
backend/
├── app.py                 # Flask app with all API endpoints
├── database.py            # SQLite setup, migrations, helpers
├── routes/admin.py        # Auth blueprint (login, logout, me, change-password)
├── reset_queue.py         # CLI tool to clear queue table
├── requirements.txt       # Python dependencies
└── queue.db               # SQLite database (auto-created)

frontend/
├── src/
│   ├── pages/             # Route components
│   │   ├── PortfolioPage.jsx    # Public landing page
│   │   ├── HomePage.jsx         # Customer queue app
│   │   ├── AdminLogin.jsx       # Admin login form
│   │   ├── AdminDashboard.jsx   # Queue management
│   │   ├── AdminSettings.jsx    # Change password
│   │   ├── AdminShopSettings.jsx# Shop configuration
│   │   ├── AdminStatistics.jsx  # Charts & analytics
│   │   └── NotFoundPage.jsx     # 404 page
│   ├── components/        # Shared components
│   │   ├── Navbar.jsx           # Top navigation
│   │   └── AdminLayout.jsx      # Admin sidebar layout
│   ├── context/           # React contexts
│   │   ├── AuthContext.jsx      # Auth state & session
│   │   ├── LocaleContext.jsx    # Arabic/English i18n
│   │   └── ThemeContext.jsx     # Dark/light theme
│   ├── utils/crypto.js    # Customer ID obfuscation
│   ├── App.jsx            # Root routing & QueueLayout
│   ├── index.css          # Global styles & Tailwind
│   └── main.jsx           # Entry point
├── index.html
├── package.json
├── tailwind.config.js
└── vite.config.js
```

## API Endpoints

### Public
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/join` | Join the queue |
| GET | `/api/queue` | Get queue state & customer info |
| POST | `/api/leave` | Leave the queue |
| GET | `/api/shop/info` | Get shop info (social, contact, hours) |

### Admin (session required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/finish` | Mark current customer as done |
| POST | `/api/skip` | Skip current or specific customer |
| POST | `/api/pause` | Pause queue (lunch/break/prayer/busy) |
| POST | `/api/resume` | Resume paused queue |
| POST | `/api/reset` | Reset queue & numbering |
| POST | `/api/toggle-open` | Open/close shop |
| POST | `/api/shop/update` | Update shop settings |
| GET | `/api/dashboard` | Dashboard data |
| GET | `/api/stats` | Analytics with period filter |

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/login` | Login (creates session) |
| POST | `/api/admin/logout` | Logout (clears session) |
| GET | `/api/admin/me` | Check session status |
| POST | `/api/admin/change-password` | Change admin password |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_SECRET_KEY` | Auto-generated random | Session signing key |
| `FLASK_DEBUG` | `0` | Enable Flask debug mode (`1`) |
| `FRONTEND_URL` | (empty) | Production frontend URL for CORS |

## Scripts

```bash
# Clear queue table
python backend/reset_queue.py        # all shops
python backend/reset_queue.py 1      # shop ID 1

# Frontend build
cd frontend && npm run build         # outputs to dist/
```

## Production Build

```bash
cd frontend
npm run build
# Copy frontend/dist/* to backend/client/
cd ../backend
python app.py
```

## Security

- Admin sessions use signed cookies (HTTP-only, SameSite=Lax)
- All modifying endpoints require an active admin session
- CORS restricted to trusted origins only (no wildcards)
- Input validation on all endpoints (string lengths, types)
- Rate limiting structure ready

## License

MIT
