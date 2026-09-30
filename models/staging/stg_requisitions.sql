-- Staging: clean types and text only. No business rules here.
-- The reporting cutoff, event flag and duration are defined in the mart.

select
    trim(cast(requisition_id as varchar)) as requisition_id,
    trim(cast(job_family as varchar)) as job_family,
    trim(cast(site as varchar)) as site,
    cast(approved_date as date) as approved_date,
    cast(offer_accepted_date as date) as offer_accepted_date
from {{ source('raw', 'requisitions') }}
