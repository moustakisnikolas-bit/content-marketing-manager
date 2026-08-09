# Recommendation Engine

## Recommendations

- what to post
- where and when to post
- content format and tone
- product/service priority
- campaign repeat/stop decision
- revision need
- boost candidate
- repurposing opportunity
- product-visibility gap

## Inputs

- publication metrics
- advertising metrics
- clicks and website events
- conversions/revenue when connected and consented
- watch time and completion
- platform/account/product/category/content type
- date, local time, timezone
- campaign goal and creative attributes
- store product status, stock, price, discount, and lifecycle

## Maturity Levels

- no data
- insufficient data
- exploratory
- account based
- product based
- category based
- hybrid
- validated

## Engine Design

Start with deterministic scoring and statistical aggregation. Add predictive models only after versioned training data, offline evaluation, controlled activation, drift monitoring, and rollback exist.

## Explainability

Every recommendation stores objective, score, confidence, evidence, sample size, data window, strategy version, expiry, and simple explanation.

Example:

> Reels performed better than static images for this product category during the measured window. Create two Reels and one Story this week.

The system must state low confidence when data is insufficient and must not invent performance evidence.
