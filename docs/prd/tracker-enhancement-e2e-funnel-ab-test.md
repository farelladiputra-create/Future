# PRD: Tracker Enhancement for Granular E2E Funnel Analysis & A/B Test

## Document Version

| PRD | Version | Date | Remarks | Author |
|---|---|---|---|---|
| Tracker Enhancement for Granular E2E Funnel Analysis & A/B Test | v1.0 | 2026-08-18 | Initial draft | Farell Adiputra |

## Background

Today's tracking cannot distinguish parent vs. addon purchases at the
transaction-property level, doesn't cover the DANA Siaga disbursement
success page, only partially covers the Rain insurance eligibility/claim
journey, and has no field-level instrumentation on the (new) Claim Form.
This blind-spots the funnel in three ways:

- **Transactions:** Analysts can't segment funnel performance or A/B test
  results by parent/addon unit type or by ribbon creative version
  (V2 vs. V3), because that context isn't attached to transaction events.
- **DANA Siaga disbursement:** There is no event marking a successful
  disbursement, so the last leg of that funnel (request → success) is
  invisible.
- **Rain insurance:** We can see that a user viewed their insurance detail
  page, but not the eligibility outcome that followed — silently expiring
  unclaimed, going ineligible due to a location change, or attempting to
  claim while ineligible. These are exactly the drop-off/edge cases the
  claims team needs to size and prioritize.
- **Claim Form:** The form is new and currently has no instrumentation at
  all, so there's no data-driven way to tell PD which fields cause the
  most drop-off, or what users do when they try to abandon the form.

## Objective

Instrument the events and properties below so that:

1. Transaction, DANA Siaga disbursement, and Rain insurance funnels can be
   analyzed end-to-end at the parent/addon and ribbon-version level,
   enabling like-for-like A/B test readouts.
2. Rain insurance eligibility edge cases (expiry without claim, location-
   driven ineligibility, ineligible claim attempts) are captured as
   discrete, queryable events.
3. The new Claim Form has field-level interaction tracking, so PD can
   identify and negotiate down the highest-friction fields, and the
   back/exit flow is tracked with the user's actual choice.

**Out of scope:** Backend/database schema changes to support disbursement
or claims processing itself, and any UI/UX changes to the flows described
below — this PRD covers analytics instrumentation only.

## Requirements & Scope of Work

### 1. Transaction Details — New Properties

Add the following properties to existing transaction-detail events (e.g.
product page view, add-to-cart, checkout, purchase-complete — **assumption:**
applied to whichever existing transaction events currently fire on these
screens; engineering to confirm the exact event list at implementation
time).

| Property | Type | Values | Notes |
|---|---|---|---|
| `transaction_unit_type` | enum | `Parent` \| `Addon` | Identifies whether the transaction line is a parent product or an addon |
| `has_addon` | boolean | `true` \| `false` | Whether this transaction includes at least one addon |
| `addon_goods_type` | string | `goodType` value | Passed through from the existing `goodType` field; only populated when `has_addon = true` |
| `ribbon_type` | enum | `Parent V2` \| `Parent V3` \| `Addon V2` \| `Addon V3` | Creative/experiment version of the ribbon shown, for A/B test attribution |

**Open question:** Confirm the exact list of existing events these
properties attach to (e.g. `Transaction Viewed`, `Transaction Completed`)
— assumed to be all events already fired on the transaction detail screen.

### 2. DANA Siaga — Success Disbursement Page

New event, fired when the DANA Siaga success disbursement page opens.

**Event:** `DANA Siaga Disbursement Success Page Viewed`

| Property | Type | Description |
|---|---|---|
| `goods_type` | string | Type of goods/product disbursed |
| `goods_title` | string | Display title of the goods/product |
| `goods_id` | string | Unique identifier of the goods/product |
| `benefit_id` | string | Unique identifier of the benefit tied to this disbursement |

### 3. Rain Insurance — Additional Eligibility & Claim Events

Three new events covering eligibility outcomes not currently captured by
the existing insurance-detail page view.

| Event | Trigger | Properties | Notes |
|---|---|---|---|
| `Insurance Claim Expired Unclaimed` | User viewed the insurance detail page while eligible, and the claim window expired without a claim being submitted | `policy_id`, `benefit_id`, `eligible_since`, `expired_at` | **Technical consideration:** this outcome can't be observed client-side at the moment it happens — it requires a backend/batch check correlating "viewed while eligible" with "no claim filed by expiry," then emitting the event server-side. |
| `Insurance Eligibility Changed to Ineligible (Location)` | A previously eligible user becomes ineligible because they moved location | `policy_id`, `benefit_id`, `previous_status=eligible`, `new_status=not_eligible`, `reason=location_change` | Same server-side/backend-detection consideration as above. |
| `Insurance Claim CTA Clicked (Ineligible)` | User on an ineligible insurance detail page taps "Ajukan Klaim" and sees the benefit bottom sheet | `policy_id`, `benefit_id`, `eligibility_status=not_eligible` | This one is a genuine client-side click event. |

### 4. Claim Form (New) — Field Friction & Exit Tracking

**a) Field-level blocker tracking**

Goal: identify which fields cause the most drop-off/friction so PD can
evaluate removing them. Proposed event, fired on field interaction:

**Event:** `Claim Form Field Interacted`

| Property | Type | Values | Notes |
|---|---|---|---|
| `field_name` | string | e.g. `policy_number`, `incident_date`, `photo_upload` | Assumption: field names to be finalized against the actual Claim Form spec |
| `action` | enum | `focused` \| `blurred` \| `error` \| `abandoned` | `abandoned` = user left the form with this field as the last one touched |
| `field_position` | number | 1, 2, 3, ... | Order of the field in the form, to build a drop-off funnel by field |

**Open question:** exact field list and whether "blocker" should be
measured by time-on-field, error rate, or abandonment — needs alignment
with PD before implementation.

**b) Exit-confirmation modal**

**Event:** `Claim Form Exit Modal Action`

Fired when the user taps back on the Claim Form (triggering the exit
confirmation modal) and resolves it.

| Property | Type | Values |
|---|---|---|
| `chosen` | enum | `PROCEED` \| `CANCEL` |

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Funnel coverage for transaction, DANA Siaga disbursement, and Rain insurance flows | 100% of steps in scope instrumented and validated in Mixpanel | Event/property QA checklist post-release |
| A/B test readouts segmentable by ribbon version and parent/addon | Available within first reporting cycle after launch | Funnel report built using `ribbon_type` and `transaction_unit_type` |
| Claim Form friction fields identified | Top 3 highest-drop-off fields identified within 4 weeks of launch | Field-level funnel from `Claim Form Field Interacted` |

## Risks & Open Questions

- Two of the three Rain insurance events depend on a backend/batch
  process rather than a client-side trigger — needs backend team scoping
  and buy-in before estimation.
- Exact set of existing transaction events to attach the new properties
  to is not yet confirmed.
- Claim Form field list and the precise definition of "blocker" (time,
  errors, or abandonment) needs PD alignment before implementation.

## Stakeholders

- **Author / Requester:** Farell Adiputra
- **Reviewers:** Product Manager (Claims/Insurance), Data/Analytics team, Mobile Engineering (iOS/Android), Backend Engineering (for server-side insurance events)

## Sign off PRD Docs

| PRD | Reason | Log Type | Log By | Date |
|---|---|---|---|---|
| | | | | |
