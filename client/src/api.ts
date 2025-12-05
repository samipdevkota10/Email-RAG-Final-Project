import type { 
  EmailResponse, 
  SearchRequest, 
  VectorSearchRequest,
  ImageSearchResponse,
  ImageTextSearchRequest,
  ImageUrlSearchRequest
} from './types'

const base = '/api' // proxied to FastAPI

export async function searchEmails(body: SearchRequest): Promise<EmailResponse> {
  const r = await fetch(`${base}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`Search failed: ${r.status}`)
  return r.json()
}

export async function fetchSnippets(limit = 5, offset = 0): Promise<EmailResponse> {
  const r = await fetch(`${base}/snippets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit, offset }),
  })
  if (!r.ok) throw new Error('Snippets failed')
  return r.json()
}

export async function searchEmailsVector(body: VectorSearchRequest): Promise<EmailResponse> {
  const r = await fetch(`${base}/search/vector`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`Vector search failed: ${r.status}`)
  return r.json()
}

export async function getDateRange() {
  const r = await fetch(`${base}/stats/date-range`)
  if (!r.ok) throw new Error('Date range failed')
  return r.json() as Promise<{ min_date: string | null; max_date: string | null; total_emails: number }>
}
export async function chatAnswer(body: {
  query: string; mode: 'vector'|'keyword';
  start?: string; end?: string; limit?: number; offset?: number; include_body?: boolean;
}) {
  const r = await fetch('/api/chat/answer', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json() as Promise<{ summary: string; citations: number[]; results: EmailResponse }>
}

// Image search APIs
export async function searchImagesByText(body: ImageTextSearchRequest): Promise<ImageSearchResponse> {
  const r = await fetch(`${base}/search/image-text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`Image text search failed: ${r.status}`)
  return r.json()
}

export async function searchImagesByImage(body: ImageUrlSearchRequest): Promise<ImageSearchResponse> {
  const r = await fetch(`${base}/search/image-image`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`Image similarity search failed: ${r.status}`)
  return r.json()
}

export async function getImageIndexStats() {
  const r = await fetch(`${base}/stats/image-index`)
  if (!r.ok) throw new Error('Image index stats failed')
  return r.json() as Promise<{ embedded: number; with_urls: number; total: number }>
}


export type EvalEmail = {
  email_id: number
  from_name: string | null
  from_address: string | null
  header_text: string | null
  snippet_text: string | null
  received_datetime: string | null
  body_html: string | null
}

export type EvalNextEmailResponse = {
  done: boolean
  email: EvalEmail | null
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export async function getNextEvalEmail(): Promise<EvalNextEmailResponse> {
  const res = await fetch(`${API_BASE}/eval/next-email`)
  if (!res.ok) throw new Error('Failed to fetch next eval email')
  return res.json()
}

export type EvalLabelPayload = {
  email_id: number
  has_offer: boolean
  offer_type?: string | null
  discount_value?: number | null
  discount_unit?: string | null
  holiday?: string | null
  notes?: string | null
  labeled_by?: string | null
}

export async function submitEvalLabel(payload: EvalLabelPayload): Promise<void> {
  const res = await fetch(`${API_BASE}/eval/label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || 'Failed to submit label')
  }
}
