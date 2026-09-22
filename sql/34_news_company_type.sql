ALTER TABLE public.news
    ADD COLUMN IF NOT EXISTS company_type TEXT;

UPDATE public.news
SET company_type = 'public'
WHERE company_type IS DISTINCT FROM 'public'
  AND (NULLIF(btrim(ticker), '') IS NOT NULL
       OR NULLIF(btrim(yf_ticker), '') IS NOT NULL);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'news_company_type_valid'
          AND conrelid = 'public.news'::regclass
    ) THEN
        ALTER TABLE public.news
            ADD CONSTRAINT news_company_type_valid
            CHECK (company_type IS NULL OR company_type IN ('public', 'private'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_news_company_type_id
    ON public.news(company_type, id DESC);
