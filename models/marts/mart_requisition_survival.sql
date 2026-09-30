-- One row per requisition approved on or before the reporting date,
-- prepared for time-to-fill survival analysis.
--
-- Rules (calendar days):
--   start             = approved_date
--   fill event        = first accepted offer, counted only if accepted on or
--                       before the reporting date
--   observation end   = offer_accepted_date if it is an event, otherwise the
--                       reporting date (the requisition is right-censored)
--   duration_days     = observation_end_date - approved_date

{% set analysis_as_of_date = "cast('" ~ var('analysis_as_of_date') ~ "' as date)" %}

with requisitions as (

    select * from {{ ref('stg_requisitions') }}

),

eligible as (

    -- Requisitions approved after the reporting date did not exist yet on that date.
    select
        *,
        {{ analysis_as_of_date }} as analysis_as_of_date
    from requisitions
    where approved_date <= {{ analysis_as_of_date }}

),

flagged as (

    -- An acceptance after the reporting date is future information.
    -- On the reporting date, that requisition was still open.
    select
        *,
        coalesce(offer_accepted_date <= analysis_as_of_date, false) as is_filled_as_of_date
    from eligible

),

observed as (

    select
        *,
        case
            when is_filled_as_of_date then offer_accepted_date
            else analysis_as_of_date
        end as observation_end_date
    from flagged

)

select
    requisition_id,
    job_family,
    site,
    approved_date,
    offer_accepted_date,
    analysis_as_of_date,
    observation_end_date,
    date_diff('day', approved_date, observation_end_date) as duration_days,
    case when is_filled_as_of_date then 1 else 0 end as event_observed,
    case when is_filled_as_of_date then 'Filled' else 'Open' end as status_as_of_date
from observed
