-- We cannot observe a requisition beyond the reporting date.
select
    requisition_id,
    observation_end_date,
    analysis_as_of_date
from {{ ref('mart_requisition_survival') }}
where observation_end_date > analysis_as_of_date
