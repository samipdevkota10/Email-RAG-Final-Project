-- Migration: Add hero image URL and image embedding columns to emails table
-- Run this script to add support for hero image extraction and embedding

-- Add hero_image_url column (stores the extracted hero image URL)
ALTER TABLE emails 
ADD COLUMN IF NOT EXISTS hero_image_url TEXT;

-- Add img_embedding column (stores the raw comprehensive image embeddings)
-- Note: Assumes pgvector extension is installed. Adjust dimension if needed.
-- The script uses ViT-L/14 which produces 768-dimensional vectors
ALTER TABLE emails 
ADD COLUMN IF NOT EXISTS img_embedding vector(768);

-- Add img_embedding_unit column (stores the L2-normalized unit vector for similarity search)
ALTER TABLE emails 
ADD COLUMN IF NOT EXISTS img_embedding_unit vector(768);

-- Create index for efficient similarity search on image embeddings
CREATE INDEX IF NOT EXISTS idx_emails_img_embedding_unit 
ON emails 
USING ivfflat (img_embedding_unit vector_cosine_ops)
WITH (lists = 100);

-- Optional: Add comment to document the columns
COMMENT ON COLUMN emails.hero_image_url IS 'URL of the extracted hero image from the email HTML body';
COMMENT ON COLUMN emails.img_embedding IS 'Raw image embedding vector (768-dim) from OpenCLIP ViT-L/14';
COMMENT ON COLUMN emails.img_embedding_unit IS 'L2-normalized unit vector for cosine similarity search (768-dim)';

