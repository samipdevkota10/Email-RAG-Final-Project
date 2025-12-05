export interface EmailSnippet {
    email_id: number
    snippet_text: string
    from_name?: string | null
    from_address?: string | null
    received_datetime?: string | null
    body_html?: string | null
    hero_image_url?: string | null
    cosine_sim?: number
  }
  
  export interface ImageHit {
    email_id: number
    hero_image_url?: string | null
    from_name?: string | null
    snippet_text?: string | null
    received_datetime?: string | null
    cosine_sim: number
  }
  
  export interface ImageSearchResponse {
    success: boolean
    count: number
    total_count: number
    items: ImageHit[]
    message: string
  }
  
  export interface EmailResponse {
    success: boolean
    count: number
    total_count: number
    emails: EmailSnippet[]
    message: string
  }
  
  export interface SearchRequest {
    query: string
    start?: string | null
    end?: string | null
    include_body?: boolean
    auto_expand?: boolean
    limit?: number
    offset?: number
  }

  export interface VectorSearchRequest {
    query: string
    start?: string | null
    end?: string | null
    limit?: number
    offset?: number
  }
  
  export interface ImageTextSearchRequest {
    text: string
    start?: string | null
    end?: string | null
    brand?: string | null
    limit?: number
    offset?: number
  }
  
  export interface ImageUrlSearchRequest {
    image_url: string
    start?: string | null
    end?: string | null
    brand?: string | null
    limit?: number
    offset?: number
  }
  