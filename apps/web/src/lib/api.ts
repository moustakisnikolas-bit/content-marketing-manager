import { apiClient } from "@/lib/api-client";

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
}

export interface OrganizationOut {
  id: string;
  name: string;
  slug: string;
}

export interface WorkspaceOut {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface SignupResponse {
  user: UserOut;
  organization: OrganizationOut;
  workspace: WorkspaceOut;
  tokens: TokenResponse;
}

export interface SubscriptionBalanceOut {
  subscription_id: string;
  credit_balance: string;
}

export interface AssetOut {
  id: string;
  workspace_id: string;
  original_filename: string;
  content_type: string;
  byte_size: number;
  created_at: string;
}

export interface CreateBriefResponse {
  content_item_id: string;
  job_id: string;
}

export interface ContentItemOut {
  id: string;
  content_type: string;
  title: string;
  status: string;
  created_at: string;
}

export interface ContentRevisionOut {
  id: string;
  revision_number: number;
  kind: string;
  text_body: string | null;
  asset_id: string | null;
  created_at: string;
}

export interface ContentPackageOut {
  id: string;
  selected_revision_id: string;
  packaged_at: string;
}

export interface ContentItemDetailOut {
  item: ContentItemOut;
  revisions: ContentRevisionOut[];
  package: ContentPackageOut | null;
}

export interface GenerationJobOut {
  id: string;
  content_item_id: string;
  status: string;
  failure_reason: string | null;
  created_at: string;
}

export type Platform = "facebook" | "instagram" | "tiktok" | "youtube";

export interface CapabilityOut {
  capability: string;
  is_available: boolean;
  reason: string | null;
}

export interface PlatformConnectionOut {
  id: string;
  platform: Platform;
  external_account_name: string;
  status: string;
  created_at: string;
}

export interface ConnectionDetailOut {
  connection: PlatformConnectionOut;
  capabilities: CapabilityOut[];
}

export interface ConnectableAccountOut {
  external_account_id: string;
  external_account_name: string;
}

export interface PendingPageSelectionOut {
  pending_token: string;
  accounts: ConnectableAccountOut[];
}

export interface PublicationPlanOut {
  id: string;
  content_item_id: string;
  platform_connection_id: string;
  status: string;
  scheduled_for: string | null;
  target_format: "post" | "story";
  failure_reason: string | null;
  created_at: string;
}

export interface PublicationAttemptOut {
  id: string;
  attempt_number: number;
  status: string;
  external_post_id: string | null;
  error_message: string | null;
}

export interface ReconciliationOut {
  matches_expected: boolean;
  external_status: string;
  checked_at: string;
}

export interface PublicationAttemptDetailOut {
  attempt: PublicationAttemptOut;
  reconciliations: ReconciliationOut[];
}

export interface MarketingGoalOut {
  id: string;
  slug: string;
  label: string;
  description: string;
}

export interface ProposedItemDraft {
  title: string;
  brief_text: string;
  platform: string | null;
}

export interface CampaignProposalOut {
  id: string;
  brief_id: string;
  objective: string;
  assumptions: string[];
  plan_summary: string;
  plan_items_draft: ProposedItemDraft[];
  estimated_cost: string;
  explanation: string;
  status: string;
}

export interface CreateMarketingBriefResponse {
  brief_id: string;
  proposal: CampaignProposalOut;
}

export interface CampaignOut {
  id: string;
  name: string;
  status: string;
  total_spent: string;
  created_at: string;
}

export interface CampaignPlanItemOut {
  id: string;
  sequence_number: number;
  title: string;
  brief_text: string;
  target_platform: string | null;
  status: string;
  content_item_id: string | null;
  publication_plan_id: string | null;
  generation_job_id: string | null;
  product_id: string | null;
  content_type: string;
}

export interface CampaignDecisionOut {
  decision_type: string;
  explanation: string;
  created_at: string;
  plan_item_id: string | null;
}

export interface CampaignDetailOut {
  campaign: CampaignOut;
  plan_items: CampaignPlanItemOut[];
  decisions: CampaignDecisionOut[];
}

export interface AutoPilotPolicyOut {
  id: string;
  allowed_platforms: string[];
  max_total_spend: string;
  blocked_topics: string[];
  posting_window_start_hour: number;
  posting_window_end_hour: number;
  kill_switch_active: boolean;
}

export interface MetricSnapshotOut {
  id: string;
  metric_definition_id: string;
  raw_provider_name: string;
  raw_payload: Record<string, unknown>;
  normalized_value: string;
  measurement_time: string;
  collection_time: string;
  publication_attempt_id: string | null;
  campaign_plan_item_id: string | null;
}

export interface MetricDefinitionOut {
  id: string;
  name: string;
  unit: string;
  scope: string;
  description: string;
}

export type RecommendationConfidence = "low" | "medium" | "high";

export interface RecommendationOut {
  id: string;
  recommendation_type: string;
  objective: string;
  score: string;
  confidence: RecommendationConfidence;
  evidence: Record<string, unknown>;
  sample_size: number;
  data_window_days: number;
  explanation: string;
  expires_at: string;
  created_at: string;
}

export interface RecommendationOutcomeOut {
  outcome: "acted_on" | "dismissed" | "expired";
  notes: string | null;
  recorded_at: string;
}

export interface RecommendationDetailOut {
  recommendation: RecommendationOut;
  outcomes: RecommendationOutcomeOut[];
}

export interface ExperimentOut {
  id: string;
  name: string;
  campaign_a_id: string;
  campaign_b_id: string;
  metric_definition_id: string;
  winner: "a" | "b" | "inconclusive";
  evidence: Record<string, unknown>;
  result_summary: string;
  created_at: string;
}

export type StorePlatform = "woocommerce" | "shopify";

export interface StoreCapabilityOut {
  capability: string;
  is_available: boolean;
  reason: string | null;
}

export interface StoreConnectionOut {
  id: string;
  platform: StorePlatform;
  store_domain: string;
  status: string;
  last_synced_at: string | null;
  created_at: string;
}

export interface StoreConnectionDetailOut {
  connection: StoreConnectionOut;
  capabilities: StoreCapabilityOut[];
}

export interface SyncProductsResponse {
  products_synced: number;
  next_cursor: string | null;
}

export interface ProductOut {
  id: string;
  store_connection_id: string;
  title: string;
  description: string;
  price: string | null;
  currency: string | null;
  status: string;
  categories: string[];
  synced_at: string;
}

export interface BulkProductCampaignResponse {
  campaign_id: string;
  started_count: number;
  failed_product_ids: string[];
}

export interface ProductVariantOut {
  id: string;
  title: string;
  sku: string | null;
  price: string | null;
}

export interface ProductAssetOut {
  url: string;
  position: number;
}

export interface ProductDetailOut {
  product: ProductOut;
  variants: ProductVariantOut[];
  assets: ProductAssetOut[];
}

export interface AgentOut {
  id: string;
  name: string;
  display_name: string;
  mcp_domain: string;
  description: string;
  status: string;
}

export interface ToolOut {
  id: string;
  agent_id: string;
  name: string;
  version: string;
  risk_level: "low" | "medium" | "high";
  description: string;
  requires_approval: boolean;
  status: string;
}

export interface ToolApprovalOut {
  id: string;
  tool_registration_id: string;
  status: string;
  destination: string | null;
  cost: string | null;
  expires_at: string;
  approved_at: string | null;
  used_at: string | null;
  created_at: string;
}

export interface ToolCallResultOut {
  authorized: boolean;
  result: Record<string, unknown>;
}

export interface RoleOut {
  id: string;
  name: string;
  permissions: string[];
}

export interface MyWorkspaceOut {
  workspace: WorkspaceOut;
  role: RoleOut;
}

export interface InvitationOut {
  id: string;
  workspace_id: string;
  email: string;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface CreateInvitationResponse {
  invitation: InvitationOut;
  invite_token: string;
}

export interface OrganizationBrandingOut {
  product_name: string | null;
  logo_url: string | null;
  primary_color: string | null;
}

export interface ApiKeyOut {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  status: string;
  last_used_at: string | null;
  created_at: string;
}

export interface CreateApiKeyResponse {
  api_key: ApiKeyOut;
  raw_key: string;
}

export interface BrandRuleOut {
  id: string;
  rule_type: string;
  description: string;
  is_blocking: boolean;
}

export interface BrandProfileOut {
  id: string;
  name: string;
  tone_description: string | null;
  product_line_description: string | null;
  vocabulary: string[];
  colors: string[];
  target_audiences: string[];
  default_ctas: string[];
  is_active: boolean;
}

export interface BrandProfileDetailOut {
  profile: BrandProfileOut;
  rules: BrandRuleOut[];
}

export interface AuditEventOut {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
  request_id: string | null;
  correlation_id: string | null;
  trace_id: string | null;
  tool_call_id: string | null;
  workflow_id: string | null;
  business_operation_id: string | null;
  created_at: string;
}

export const api = {
  signup: (payload: {
    email: string;
    password: string;
    display_name: string;
    organization_name: string;
  }) => apiClient.post<SignupResponse>("/auth/signup", payload, { auth: false }),

  login: (payload: { email: string; password: string }) =>
    apiClient.post<TokenResponse>("/auth/login", payload, { auth: false }),

  me: () => apiClient.get<UserOut>("/auth/me"),

  getSubscriptionBalance: () => apiClient.get<SubscriptionBalanceOut>("/billing/subscription"),

  listAssets: () => apiClient.get<AssetOut[]>("/assets"),

  uploadAsset: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.post<AssetOut>("/assets/upload", formData);
  },

  getAssetDownloadUrl: (assetId: string) => apiClient.get<{ url: string }>(`/assets/${assetId}/download-url`),

  createBrief: (payload: {
    content_type: "text" | "image" | "audio";
    title: string;
    brief_text: string;
    brand_profile_id?: string;
  }) => apiClient.post<CreateBriefResponse>("/content/briefs", payload),

  listContentItems: () => apiClient.get<ContentItemOut[]>("/content/items"),

  getContentItem: (itemId: string) =>
    apiClient.get<ContentItemDetailOut>(`/content/items/${itemId}`),

  getGenerationJob: (jobId: string) =>
    apiClient.get<GenerationJobOut>(`/content/jobs/${jobId}`),

  reviewGenerationJob: (
    jobId: string,
    payload: { decision: "approved" | "rejected"; revision_id: string; comment?: string },
  ) => apiClient.post<{ status: string; new_job_id: string | null }>(`/content/jobs/${jobId}/review`, payload),

  listGenerationJobs: () => apiClient.get<GenerationJobOut[]>("/content/jobs"),

  getAuthorizationUrl: (platform: Platform) =>
    apiClient.get<{ authorization_url: string }>(`/publishing/oauth/authorize?platform=${platform}`),

  completeOAuthCallback: (code: string, state: string) =>
    apiClient.get<ConnectionDetailOut | PendingPageSelectionOut>(
      `/publishing/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
      { auth: false },
    ),

  selectPage: (pendingToken: string, externalAccountId: string) =>
    apiClient.post<ConnectionDetailOut>(
      "/publishing/oauth/select-page",
      { pending_token: pendingToken, external_account_id: externalAccountId },
      { auth: false },
    ),

  listConnections: () => apiClient.get<ConnectionDetailOut[]>("/publishing/connections"),

  createPublicationPlan: (payload: {
    content_item_id: string;
    platform_connection_id: string;
    scheduled_for?: string;
    target_format?: "post" | "story";
  }) => apiClient.post<{ plan_id: string }>("/publishing/plans", payload),

  listPublicationPlans: () => apiClient.get<PublicationPlanOut[]>("/publishing/plans"),

  getPublicationPlan: (planId: string) => apiClient.get<PublicationPlanOut>(`/publishing/plans/${planId}`),

  listPublicationAttempts: (planId: string) =>
    apiClient.get<PublicationAttemptDetailOut[]>(`/publishing/plans/${planId}/attempts`),

  reviewPublicationPlan: (planId: string, payload: { decision: "approved" | "rejected"; comment?: string }) =>
    apiClient.post<{ status: string }>(`/publishing/plans/${planId}/review`, payload),

  listMarketingGoals: () => apiClient.get<MarketingGoalOut[]>("/marketing/goals"),

  createMarketingBrief: (payload: {
    goal_slug: string;
    what_to_promote: string;
    mode: "manual" | "guided" | "autopilot";
    target_platforms: string[];
  }) => apiClient.post<CreateMarketingBriefResponse>("/marketing/briefs", payload),

  approveProposal: (proposalId: string, payload: { campaign_name: string }) =>
    apiClient.post<{ campaign_id: string }>(`/marketing/proposals/${proposalId}/approve`, payload),

  listCampaigns: () => apiClient.get<CampaignOut[]>("/marketing/campaigns"),

  cancelCampaign: (campaignId: string) => apiClient.post<CampaignOut>(`/marketing/campaigns/${campaignId}/cancel`),

  getCampaign: (campaignId: string) => apiClient.get<CampaignDetailOut>(`/marketing/campaigns/${campaignId}`),

  startPlanItem: (campaignId: string, itemId: string) =>
    apiClient.post<{ status: string; job_id: string }>(`/marketing/campaigns/${campaignId}/items/${itemId}/start`),

  removePlanItem: (campaignId: string, itemId: string) =>
    apiClient.post<{ status: string }>(`/marketing/campaigns/${campaignId}/items/${itemId}/remove`),

  createAutoPilotPolicy: (
    campaignId: string,
    payload: {
      allowed_platforms: string[];
      max_total_spend: string;
      blocked_topics: string[];
      posting_window_start_hour: number;
      posting_window_end_hour: number;
    },
  ) => apiClient.post<AutoPilotPolicyOut>(`/marketing/campaigns/${campaignId}/autopilot-policy`, payload),

  getAutoPilotPolicy: (campaignId: string) =>
    apiClient.get<AutoPilotPolicyOut>(`/marketing/campaigns/${campaignId}/autopilot-policy`),

  startAutoPilot: (campaignId: string) =>
    apiClient.post<{ status: string; workflow_id: string }>(`/marketing/campaigns/${campaignId}/autopilot/start`),

  haltAutoPilot: (campaignId: string) =>
    apiClient.post<{ status: string }>(`/marketing/campaigns/${campaignId}/autopilot/halt`),

  listMetricDefinitions: () => apiClient.get<MetricDefinitionOut[]>("/analytics/metric-definitions"),

  ingestMetrics: (publicationAttemptId: string) =>
    apiClient.post<{ snapshots: MetricSnapshotOut[] }>("/analytics/ingest", {
      publication_attempt_id: publicationAttemptId,
    }),

  listSnapshotsForAttempt: (attemptId: string) =>
    apiClient.get<MetricSnapshotOut[]>(`/analytics/attempts/${attemptId}/snapshots`),

  listRecommendations: () => apiClient.get<RecommendationOut[]>("/analytics/recommendations"),

  getRecommendation: (recommendationId: string) =>
    apiClient.get<RecommendationDetailOut>(`/analytics/recommendations/${recommendationId}`),

  generateBestPostingTime: (payload?: { metric_name?: string; data_window_days?: number }) =>
    apiClient.post<RecommendationOut>("/analytics/recommendations/best-posting-time", payload ?? {}),

  recordRecommendationOutcome: (
    recommendationId: string,
    payload: { outcome: "acted_on" | "dismissed" | "expired"; notes?: string },
  ) => apiClient.post<RecommendationOutcomeOut>(`/analytics/recommendations/${recommendationId}/outcomes`, payload),

  listExperiments: () => apiClient.get<ExperimentOut[]>("/analytics/experiments"),

  generateCampaignComparison: (payload: {
    name: string;
    campaign_a_id: string;
    campaign_b_id: string;
    metric_name?: string;
  }) => apiClient.post<ExperimentOut>("/analytics/experiments/campaign-comparison", payload),

  getStoreAuthorizationUrl: (platform: StorePlatform) =>
    apiClient.get<{ authorization_url: string }>(`/commerce/oauth/authorize?platform=${platform}`),

  completeStoreOAuthCallback: (code: string, state: string) =>
    apiClient.get<StoreConnectionDetailOut>(
      `/commerce/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
      { auth: false },
    ),

  connectStoreWithCredentials: (payload: {
    platform: "woocommerce";
    store_domain: string;
    consumer_key: string;
    consumer_secret: string;
  }) => apiClient.post<StoreConnectionDetailOut>("/commerce/connect/api-key", payload),

  createPluginPairingCode: () =>
    apiClient.post<{ pairing_token: string; expires_in_minutes: number }>("/commerce/connect/plugin-pairing-code"),

  listStores: () => apiClient.get<StoreConnectionDetailOut[]>("/commerce/stores"),

  deleteStore: (connectionId: string) => apiClient.delete<void>(`/commerce/stores/${connectionId}`),

  syncStoreProducts: (connectionId: string) =>
    apiClient.post<SyncProductsResponse>(`/commerce/stores/${connectionId}/sync`),

  listProducts: () => apiClient.get<ProductOut[]>("/commerce/products"),

  getProduct: (productId: string) => apiClient.get<ProductDetailOut>(`/commerce/products/${productId}`),

  generateProductCampaign: (
    productId: string,
    payload: { goal_slug: string; mode: "manual" | "guided" | "autopilot"; target_platforms: string[] },
  ) => apiClient.post<CampaignProposalOut>(`/commerce/products/${productId}/campaign`, payload),

  bulkGenerateProductCampaign: (payload: {
    product_ids: string[];
    description: string;
    goal_slug: string;
    target_platforms: string[];
    campaign_id?: string | null;
    generate_images?: boolean;
  }) => apiClient.post<BulkProductCampaignResponse>("/commerce/products/bulk-campaign", payload),

  generateAbandonedCartContent: (productId: string, payload: { consent_confirmed: boolean }) =>
    apiClient.post<CampaignProposalOut>(`/commerce/products/${productId}/abandoned-cart-content`, payload),

  listAgents: () => apiClient.get<AgentOut[]>("/governance/agents"),

  listGovernanceTools: () => apiClient.get<ToolOut[]>("/governance/tools"),

  listPendingToolApprovals: () => apiClient.get<ToolApprovalOut[]>("/governance/approvals"),

  requestToolApproval: (payload: { tool_id: string; payload: Record<string, unknown>; destination?: string }) =>
    apiClient.post<ToolApprovalOut>("/governance/approvals", payload),

  approveToolApproval: (approvalId: string) =>
    apiClient.post<ToolApprovalOut>(`/governance/approvals/${approvalId}/approve`),

  callGenerateProductCampaignTool: (payload: {
    product_id: string;
    goal_slug: string;
    mode: "manual" | "guided" | "autopilot";
    target_platforms: string[];
  }) => apiClient.post<ToolCallResultOut>("/governance/tools/generate-product-campaign/call", payload),

  callGenerateBestPostingTimeTool: (payload?: { metric_name?: string; data_window_days?: number }) =>
    apiClient.post<ToolCallResultOut>("/governance/tools/generate-best-posting-time/call", payload ?? {}),

  getAuditTrail: (correlationId: string) =>
    apiClient.get<AuditEventOut[]>(`/governance/audit-trail?correlation_id=${encodeURIComponent(correlationId)}`),

  listMyWorkspaces: () => apiClient.get<MyWorkspaceOut[]>("/organizations/workspaces"),

  createWorkspace: (payload: { name: string }) =>
    apiClient.post<WorkspaceOut>("/organizations/workspaces", payload),

  createInvitation: (workspaceId: string, payload: { email: string; role_name: string }) =>
    apiClient.post<CreateInvitationResponse>(`/organizations/workspaces/${workspaceId}/invitations`, payload),

  listPendingInvitations: (workspaceId: string) =>
    apiClient.get<InvitationOut[]>(`/organizations/workspaces/${workspaceId}/invitations`),

  acceptInvitation: (token: string) =>
    apiClient.post<{ workspace_id: string; status: string }>("/organizations/invitations/accept", { token }),

  getOrganizationBranding: () => apiClient.get<OrganizationBrandingOut>("/organizations/branding"),

  updateOrganizationBranding: (payload: {
    product_name?: string | null;
    logo_url?: string | null;
    primary_color?: string | null;
  }) => apiClient.put<OrganizationBrandingOut>("/organizations/branding", payload),

  createApiKey: (payload: { name: string; scopes: string[] }) =>
    apiClient.post<CreateApiKeyResponse>("/api-keys", payload),

  listApiKeys: () => apiClient.get<ApiKeyOut[]>("/api-keys"),

  revokeApiKey: (apiKeyId: string) => apiClient.post<ApiKeyOut>(`/api-keys/${apiKeyId}/revoke`),

  listBrandProfiles: () => apiClient.get<BrandProfileOut[]>("/brand-profiles"),

  getBrandProfile: (profileId: string) => apiClient.get<BrandProfileDetailOut>(`/brand-profiles/${profileId}`),

  createBrandProfile: (payload: {
    name: string;
    tone_description?: string | null;
    product_line_description?: string | null;
    vocabulary: string[];
    colors: string[];
    target_audiences: string[];
    default_ctas: string[];
  }) => apiClient.post<BrandProfileOut>("/brand-profiles", payload),

  updateBrandProfile: (
    profileId: string,
    payload: {
      name: string;
      tone_description?: string | null;
      product_line_description?: string | null;
      vocabulary: string[];
      colors: string[];
      target_audiences: string[];
      default_ctas: string[];
      is_active: boolean;
    },
  ) => apiClient.put<BrandProfileOut>(`/brand-profiles/${profileId}`, payload),

  addBrandRule: (profileId: string, payload: { rule_type: string; description: string; is_blocking: boolean }) =>
    apiClient.post<BrandRuleOut>(`/brand-profiles/${profileId}/rules`, payload),

  deleteBrandRule: (ruleId: string) => apiClient.delete<void>(`/brand-profiles/rules/${ruleId}`),
};
