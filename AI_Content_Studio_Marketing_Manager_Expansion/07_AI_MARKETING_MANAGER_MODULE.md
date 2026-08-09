# AI Marketing Manager Module

## Purpose

AI Marketing Manager is the intelligence and orchestration layer above content creation. It translates a business goal into a measurable campaign proposal and coordinates creation, approval, scheduling, publishing, analytics, and improvement.

## Supported Goals

- more sales
- more messages or bookings
- more website traffic
- more followers or engagement
- brand awareness
- product/service launch
- offer announcement
- product education
- retargeting content
- seasonal or evergreen promotion

## Guided Wizard

1. Choose what to promote.
2. Add product, service, URL, image, media, brand, or prior-campaign inputs.
3. Choose Manual, Guided, or Auto-Pilot.
4. Choose supported platforms.
5. Choose the goal and measurable target.
6. Receive a campaign proposal.
7. Approve, edit, regenerate, change tone, reduce cost, or request stronger marketing.
8. Publish now, schedule, auto-select time, save draft, create variants, send for review, or export.

## Campaign Proposal

Must contain:

- campaign name and objective
- assumptions and missing inputs
- content plan and calendar
- destination platforms
- recommended formats
- required assets
- captions, hashtags, CTA direction
- visual/video/audio direction
- variants and experiment plan
- estimated usage and cost
- expected measurable outcome definition
- beginner explanation
- internal decision/evidence record

## Backend Services

- MarketingBriefService
- CampaignProposalService
- CampaignRecipeService
- CampaignOrchestrationService
- GoalDefinitionService
- VariantExperimentService
- CampaignEligibilityService
- CampaignExplanationService

## Data Model

- MarketingGoal
- MarketingBrief
- CampaignProposal
- CampaignStrategyVersion
- CampaignObjectiveMetric
- CampaignAssetRequirement
- CampaignVariant
- CampaignDecision
- CampaignOutcome

## What Is Needed to Work

- confirmed Brand and Product/Service Profiles
- platform connections and capabilities
- content recipes and price snapshots
- analytics normalization
- attribution inputs where available
- recommendation profiles and strategy versions
- approval policies and audit trail
- provider routing and content-quality gates
- campaign orchestration workers
- clear consent and auto-pilot boundaries
