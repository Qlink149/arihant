from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LeadBase(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    work_phone: Optional[str] = None
    email: Optional[str] = None
    project: Optional[str] = None
    project_id: Optional[str] = None
    pipeline_category: Optional[str] = None
    lead_status: Optional[str] = "New"
    lead_source: Optional[str] = None
    original_source: Optional[str] = None
    most_recent_source: Optional[str] = None
    original_fw_status: Optional[str] = None
    is_rnr: bool = False
    budget: Optional[str] = None
    configuration: Optional[str] = None
    unit_size: Optional[str] = None
    location: Optional[str] = None
    ethnicity: Optional[str] = None
    designation: Optional[str] = None
    reason_for_purchase: Optional[str] = None
    possession_requirement: Optional[str] = None
    current_residence_type: Optional[str] = None
    campaign_name: Optional[str] = None
    presales_agent: Optional[str] = None
    presales_description: Optional[str] = None
    next_action_date: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    visit_date_dt: Optional[datetime] = Field(default=None, description="Native BSON datetime for scheduled visits")
    site_visit_count: Optional[int] = 0
    meta_qualified: Optional[bool] = None
    temperature: Optional[str] = None
    # Website / public intake fields
    consent: Optional[bool] = None
    schedule_visit: Optional[str] = None
    intake_meta: Optional[Dict[str, Any]] = None
    submission_count: Optional[int] = None
    intake_spam: Optional[bool] = None


class LeadCreate(LeadBase):
    model_config = ConfigDict(extra="ignore")


class LeadUpdatePatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    work_phone: Optional[str] = None
    email: Optional[str] = None
    project: Optional[str] = None
    pipeline_category: Optional[str] = None
    lead_status: Optional[str] = None
    lead_source: Optional[str] = None
    original_source: Optional[str] = None
    most_recent_source: Optional[str] = None
    budget: Optional[str] = None
    configuration: Optional[str] = None
    unit_size: Optional[str] = None
    location: Optional[str] = None
    ethnicity: Optional[str] = None
    designation: Optional[str] = None
    reason_for_purchase: Optional[str] = None
    possession_requirement: Optional[str] = None
    current_residence_type: Optional[str] = None
    campaign_name: Optional[str] = None
    presales_agent: Optional[str] = None
    presales_description: Optional[str] = None
    next_action_date: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    visit_date_dt: Optional[datetime] = None
    site_visit_count: Optional[int] = None
    meta_qualified: Optional[bool] = None
    temperature: Optional[str] = None
    vip: Optional[bool] = None
    vip_manual: Optional[bool] = None
    # Outcome logging (Contacted stage SLA suppression; validated in service layer)
    logged_outcome: Optional[str] = None
    logged_outcome_reason: Optional[str] = None
    # Lost/Junk reason
    lost_reason: Optional[str] = None
    consent: Optional[bool] = None
    schedule_visit: Optional[str] = None
    intake_meta: Optional[Dict[str, Any]] = None
    submission_count: Optional[int] = None
    intake_spam: Optional[bool] = None


class LeadResponse(LeadBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    normalized_phone: Optional[str] = None
    normalized_work_phone: Optional[str] = None
    recent_note: Optional[str] = None
    temperature: Optional[str] = None
    intent: str = "Unknown"
    vip: bool = False
    vip_manual: Optional[bool] = None
    assigned_to: Optional[str] = None
    nurture_entered_at_dt: Optional[datetime] = None
    interested_entered_at_dt: Optional[datetime] = None
    rnr_entered_at_dt: Optional[datetime] = None
    contacted_at_dt: Optional[datetime] = None
    visit_completed_at_dt: Optional[datetime] = None
    sv_followup_entered_at_dt: Optional[datetime] = None
    sv_followup_1_entered_at_dt: Optional[datetime] = None
    sv_followup_2_entered_at_dt: Optional[datetime] = None
    gone_cold_entered_at_dt: Optional[datetime] = None
    negotiation_entered_at_dt: Optional[datetime] = None
    future_prospect_entered_at_dt: Optional[datetime] = None
    fp_cycle_count: Optional[int] = None
    fp_last_checkin_task_created_at_dt: Optional[datetime] = None
    logged_outcome: Optional[str] = None
    logged_outcome_reason: Optional[str] = None
    lost_reason: Optional[str] = None
    nurture_task_required_since_dt: Optional[datetime] = None
    nurture_task_required_task_id: Optional[str] = None
    import_provenance: Optional[str] = None
    sla_paused: Optional[bool] = None
    sla_activated_at_dt: Optional[datetime] = None
    ai_persona_summary: Optional[str] = None
    strategic_next_moves: List[Dict[str, Any]] = Field(default_factory=list)
    ai_grounded_profile: Optional[Dict[str, str]] = None
    ai_last_generated_at: Optional[datetime] = None
    ai_configured: Optional[bool] = None
    ai_stale: Optional[bool] = None
    ai_generation_pending: Optional[bool] = None
    consent: Optional[bool] = None
    schedule_visit: Optional[str] = None
    intake_meta: Optional[Dict[str, Any]] = None
    submission_count: Optional[int] = None
    intake_spam: Optional[bool] = None
    context_updates: List[dict] = []
    created_at: datetime
    updated_at: datetime
