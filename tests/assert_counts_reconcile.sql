-- Every requisition approved on or before the reporting date appears once in
-- the mart, and filled + censored (open) adds up to the total.
with expected as (

    select count(*) as eligible_requisitions
    from {{ ref('stg_requisitions') }}
    where approved_date <= cast('{{ var("analysis_as_of_date") }}' as date)

),

actual as (

    select
        count(*) as total_requisitions,
        count(*) filter (where event_observed = 1) as filled_requisitions,
        count(*) filter (where event_observed = 0) as censored_requisitions
    from {{ ref('mart_requisition_survival') }}

)

select *
from expected
cross join actual
where total_requisitions <> eligible_requisitions
   or filled_requisitions + censored_requisitions <> total_requisitions
