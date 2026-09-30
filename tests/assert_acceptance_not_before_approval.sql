-- An offer cannot be accepted before the requisition was approved.
-- Returns the rows that break the rule; the test passes when none are returned.
select
    requisition_id,
    approved_date,
    offer_accepted_date
from {{ ref('stg_requisitions') }}
where offer_accepted_date < approved_date
