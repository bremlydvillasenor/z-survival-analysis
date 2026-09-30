-- Time to fill can be zero or more days, never negative.
select
    requisition_id,
    duration_days
from {{ ref('mart_requisition_survival') }}
where duration_days < 0
