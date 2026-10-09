# Control Tower (frontend)
npm install && cp .env.example .env && npm run dev   # mock data on by default; set VITE_USE_MOCK=false for the real API
Backend contract lives in src/api/types.ts. Expected endpoints:
GET /shipments?status=in_transit | POST /agent/investigate (SSE) | POST /rag/ask | POST /decisions
