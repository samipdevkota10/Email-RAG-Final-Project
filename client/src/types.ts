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
  
  export interface AnalyticsOffer extends EmailSnippet {
    offer_id: number
    discount_type?: string | null
    percent_off?: number | null
    amount_off?: number | null
    currency?: string | null
    is_up_to?: boolean
    min_spend?: number | null
    promo_code?: string | null
    confidence?: number | null
    offer_text?: string | null
    company_name?: string | null
    primary_industry?: string | null
    secondary_industry?: string | null
    tertiary_industry?: string | null
    iso_year?: number | null
    iso_week?: number | null
    week_rank?: number | null
  }
  
  export interface AnalyticsOffersRequest {
    year: number
    week?: number | null
    industry?: string | null
    top_n?: number
    sort_by?: 'week' | 'percent' | 'amount'
    include_other_types?: boolean
  }
  
  export interface AnalyticsOffersResponse {
    success: boolean
    count: number
    total_count: number
    offers: AnalyticsOffer[]
    message: string
  }
  
  export interface AnalyticsSummaryRequest {
    year: number
    week?: number | null
    industry?: string | null
    offer_ids?: number[] | null
  }
  
  export interface AnalyticsSummaryResponse {
    summary: string
    citations: number[]
  }

  // New analytics types for enhanced dashboard
  export interface HeadlineStats {
    total_active_offers: number
    avg_market_discount: number
    top_industry: string | null
  }

  export interface DiscountBucket {
    bucket_label: string
    bucket_min: number
    bucket_max: number
    count: number
    percentage: number
    avg_in_bucket?: number | null
  }

  export interface DiscountDistribution {
    total_offers: number
    avg_discount: number
    median_discount?: number | null
    min_discount: number
    max_discount: number
    std_dev?: number | null
    buckets: DiscountBucket[]
  }

  export interface WeeklyStat {
    week: number
    avg_discount: number
    volume: number
    wow_change: number | null  // Week-over-week change
  }
  